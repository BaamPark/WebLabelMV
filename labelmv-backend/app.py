
from flask import Flask, request, jsonify, Response
from flask import send_file
from flask_cors import CORS
import os
import json
import jwt
import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_pymongo import PyMongo
from functools import wraps
from bson import ObjectId
import cv2
import math
import io

from agent_prompting import (
    build_contextual_chat_prompt,
    log_agent_input,
    select_box_subset,
    serialize_boxes_for_prompt,
)
from chatbot_service import ChatbotProxyService, load_chatbot_config, ChatbotServiceError

app = Flask(__name__)
CORS(app)

# Configure MongoDB connection via env var for containerization
app.config['MONGO_URI'] = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/labelmv')
mongo = PyMongo(app)

# Secret key for JWT via env var
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'changeme-in-prod')
chatbot_config = load_chatbot_config()
app.config['MAX_CONTENT_LENGTH'] = max(
    chatbot_config.max_image_bytes + 1024 * 1024,
    int(os.environ.get('MAX_CONTENT_LENGTH', chatbot_config.max_image_bytes + 1024 * 1024))
)
chatbot_service = ChatbotProxyService(chatbot_config)

# In-memory storage for annotations (for simplicity, will be replaced with database)
annotations_storage = {}

def _coerce_project_id(project_id):
    if isinstance(project_id, ObjectId):
        return project_id
    if isinstance(project_id, str) and ObjectId.is_valid(project_id):
        return ObjectId(project_id)
    if isinstance(project_id, str):
        return project_id
    return None


def _sanitize_attributes(raw_attributes):
    attributes = {}
    if not isinstance(raw_attributes, dict):
        return attributes

    for key, value in raw_attributes.items():
        if not isinstance(key, str) or not isinstance(value, list):
            continue
        options = [str(item) for item in value if isinstance(item, (str, int, float))]
        if options:
            attributes[key] = options
    return attributes


def _sanitize_attribute_descriptions(raw_descriptions, attributes):
    descriptions = {}
    if not isinstance(raw_descriptions, dict):
        return descriptions

    for attr_name, code_map in raw_descriptions.items():
        if not isinstance(attr_name, str) or not isinstance(code_map, dict):
            continue
        valid_codes = set(attributes.get(attr_name) or [])
        if not valid_codes:
            continue

        normalized = {}
        for code, description in code_map.items():
            if not isinstance(code, str) or code not in valid_codes:
                continue
            if not isinstance(description, str):
                continue
            text = description.strip()
            if text:
                normalized[code] = text

        if normalized:
            descriptions[attr_name] = normalized
    return descriptions


def _get_owned_project(current_user, project_id):
    pid_key = _coerce_project_id(project_id)
    if pid_key is None:
        return None
    project = mongo.db.projects.find_one({'_id': pid_key})
    if not project or project.get('user_id') != str(current_user['_id']):
        return None
    return project


def _get_annotation_boxes_for(user_id, project_id, video_index, sample_index):
    doc = mongo.db.annotations.find_one({
        'user_id': str(user_id),
        'project_id': str(project_id),
        'video_index': int(video_index),
        'sample_index': int(sample_index),
    })
    boxes = doc.get('boxes') if doc else []
    return boxes if isinstance(boxes, list) else []


def _read_frame_bytes(project, video_index, sample_index):
    info, err = _video_info_for(project, video_index)
    if err:
        msg, code = err
        raise ChatbotServiceError(msg, status_code=code)

    step = info['step']
    total_frames = info['total_frames']
    frame_num = min(sample_index * step, max(0, total_frames - 1))

    cap = cv2.VideoCapture(info['video_path'])
    if not cap.isOpened():
        raise ChatbotServiceError("Failed to open video", status_code=500)

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise ChatbotServiceError("Failed to read frame", status_code=500)

    ok, buf = cv2.imencode('.jpg', frame)
    if not ok:
        raise ChatbotServiceError("Failed to encode frame", status_code=500)

    return buf.tobytes(), info

@app.route('/videos', methods=['GET'])
def get_videos():
    directory = request.args.get('directory') or '/app/videos'
    if not os.path.isdir(directory):
        return jsonify({"error": "Invalid directory path"}), 400

    video_files = []
    for file in os.listdir(directory):
        if file.endswith(('.mp4', '.avi', '.mov', '.mkv')):
            video_files.append(file)

    return jsonify(video_files)

# User registration endpoint
@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.get_json()

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    # Check if user already exists
    existing_user = mongo.db.users.find_one({"username": username})
    if existing_user:
        return jsonify({"error": "User already exists"}), 400

    # Hash the password and store user in database
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    mongo.db.users.insert_one({
        "username": username,
        "password": hashed_password
    })

    return jsonify({"message": "User registered successfully"}), 201

# User login endpoint
@app.route('/api/auth/signin', methods=['POST'])
def signin():
    data = request.get_json()

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    # Find user in database
    user = mongo.db.users.find_one({"username": username})

    if not user or not check_password_hash(user['password'], password):
        return jsonify({"error": "Invalid credentials"}), 401

    # Create JWT token
    token = jwt.encode({
        'user_id': str(user['_id']),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }, app.config['SECRET_KEY'], algorithm="HS256")

    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return jsonify({"token": token})

# Middleware to verify JWT token
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]

        if not token:
            return jsonify({"error": "Token is missing"}), 403

        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = mongo.db.users.find_one({"_id": ObjectId(data['user_id'])})
        except Exception as e:
            return jsonify({"error": "Token is invalid", "message": str(e)}), 403

        return f(current_user, *args, **kwargs)

    return decorated

# API endpoint to save annotations for a specific video
@app.route('/api/annotations/<int:video_id>', methods=['POST'])
@token_required
def save_annotations(current_user, video_id):
    data = request.get_json()

    if data is None:
        return jsonify({"error": "Invalid input"}), 400

    # Store annotations in memory with user ID and video ID as key
    user_id = str(current_user['_id'])
    annotations_storage[(user_id, video_id)] = data

    return jsonify({"success": True, "message": f"Annotations saved for video {video_id}"})

# API endpoint to get annotations for a specific video
@app.route('/api/annotations/<int:video_id>', methods=['GET'])
@token_required
def get_annotations(current_user, video_id):
    # Retrieve annotations from memory
    user_id = str(current_user['_id'])
    annotations = annotations_storage.get((user_id, video_id), [])

    return jsonify(annotations)


@app.route('/api/chatbot', methods=['POST'])
@token_required
def chatbot(current_user):
    if request.content_type and request.content_type.startswith('application/json'):
        data = request.get_json(silent=True) or {}
        text = (data.get('text') or '').strip()
        project_id = data.get('project_id') or data.get('projectId')
        source_video_index = data.get('source_video_index')
        source_sample_index = data.get('source_sample_index')
        target_scope = data.get('target_scope') or 'none'
        target_video_index = data.get('target_video_index')
        target_sample_index = data.get('target_sample_index')
        target_box_id = data.get('target_box_id') or 'none'
        selected_box_id = data.get('selected_box_id')
        current_boxes_raw = data.get('current_boxes') or []
        chat_history_raw = data.get('chat_history') or []
    else:
        text = (request.form.get('text') or '').strip()
        project_id = request.form.get('project_id')
        source_video_index = request.form.get('source_video_index')
        source_sample_index = request.form.get('source_sample_index')
        target_scope = request.form.get('target_scope') or 'none'
        target_video_index = request.form.get('target_video_index')
        target_sample_index = request.form.get('target_sample_index')
        target_box_id = request.form.get('target_box_id') or 'none'
        selected_box_id = request.form.get('selected_box_id')
        current_boxes_raw = request.form.get('current_boxes') or '[]'
        chat_history_raw = request.form.get('chat_history') or '[]'

    try:
        current_boxes = current_boxes_raw if isinstance(current_boxes_raw, list) else json.loads(current_boxes_raw)
    except (TypeError, ValueError):
        current_boxes = []
    if not isinstance(current_boxes, list):
        current_boxes = []

    try:
        chat_history = chat_history_raw if isinstance(chat_history_raw, list) else json.loads(chat_history_raw)
    except (TypeError, ValueError):
        chat_history = []
    if not isinstance(chat_history, list):
        chat_history = []
    normalized_chat_history = []
    for item in chat_history:
        if not isinstance(item, dict):
            continue
        role = (item.get('role') or '').strip()
        text_value = (item.get('text') or '').strip()
        if role and text_value:
            normalized_chat_history.append({
                'role': role,
                'text': text_value,
            })

    contextual_text = text
    contextual_images = []

    if project_id:
        project = _get_owned_project(current_user, project_id)
        if not project:
            return jsonify({"error": "Project not found or unauthorized"}), 404

        try:
            source_video_index = int(source_video_index)
            source_sample_index = int(source_sample_index)
        except (TypeError, ValueError):
            return jsonify({"error": "source_video_index and source_sample_index are required"}), 400

        try:
            source_frame_bytes, _source_info = _read_frame_bytes(project, source_video_index, source_sample_index)
        except ChatbotServiceError as error:
            return jsonify({"error": error.message}), error.status_code

        source_boxes = current_boxes
        if not source_boxes:
            source_boxes = _get_annotation_boxes_for(
                current_user['_id'],
                project['_id'],
                source_video_index,
                source_sample_index,
            )

        contextual_images.append({
            'bytes': source_frame_bytes,
            'mime_type': 'image/jpeg',
            'filename': f"source_view_{source_video_index}_frame_{source_sample_index}.jpg",
        })
        boxes_for_current_frame = None
        target_box = None
        selected_boxes = serialize_boxes_for_prompt(select_box_subset(source_boxes, target_box_id))
        if target_box_id == 'all':
            boxes_for_current_frame = serialize_boxes_for_prompt(source_boxes)
        elif target_box_id not in (None, '', 'none'):
            target_box = selected_boxes[0] if selected_boxes else None
        has_additional_frame = False

        if target_scope != 'none':
            try:
                target_video_index = int(target_video_index)
                target_sample_index = int(target_sample_index)
            except (TypeError, ValueError):
                return jsonify({"error": "target frame metadata is invalid"}), 400

            try:
                target_frame_bytes, _target_info = _read_frame_bytes(project, target_video_index, target_sample_index)
            except ChatbotServiceError as error:
                return jsonify({"error": error.message}), error.status_code

            has_additional_frame = True
            contextual_images.append({
                'bytes': target_frame_bytes,
                'mime_type': 'image/jpeg',
                'filename': f"target_view_{target_video_index}_frame_{target_sample_index}.jpg",
            })

        contextual_text = build_contextual_chat_prompt(
            text,
            project,
            has_additional_frame=has_additional_frame,
            boxes_for_current_frame=boxes_for_current_frame,
            target_box=target_box,
            chat_history=normalized_chat_history,
        )

    log_agent_input(
        current_user['_id'],
        project_id,
        contextual_text,
        contextual_images,
    )

    try:
        reply = chatbot_service.generate_reply(
            text=contextual_text,
            images=contextual_images,
        )
    except ChatbotServiceError as error:
        return jsonify({"error": error.message}), error.status_code

    return jsonify({
        "reply": reply,
        "model": chatbot_config.model_id,
        "provider": chatbot_config.provider,
        "baseUrl": chatbot_config.base_url,
    })

# -------- Project + Frame APIs --------

@app.route('/api/projects', methods=['POST'])
@token_required
def create_or_update_project(current_user):
    data = request.get_json(silent=True) or {}
    video_directory = data.get('videoDirectory')
    selected_videos = data.get('selectedVideos') or []
    fps = data.get('fps')
    classes = data.get('classes') or []
    # optional project-level attributes: { name: [option1, option2, ...], ... }
    raw_attributes = data.get('attributes') or {}
    raw_attribute_descriptions = data.get('attributeDescriptions') or {}
    project_id = data.get('projectId')  # optional for update/create

    if not video_directory or not isinstance(selected_videos, list) or not fps:
        return jsonify({"error": "videoDirectory, selected_videos and fps are required"}), 400
    if not isinstance(classes, list):
        return jsonify({"error": "classes must be a list"}), 400
    attributes = _sanitize_attributes(raw_attributes)
    attribute_descriptions = _sanitize_attribute_descriptions(raw_attribute_descriptions, attributes)

    doc = {
        'user_id': str(current_user['_id']),
        'video_directory': video_directory,
        'selected_videos': selected_videos,
        'fps': int(fps),
        'classes': classes,
        'attributes': attributes,
        'attribute_descriptions': attribute_descriptions,
        'updated_at': datetime.datetime.utcnow(),
    }

    if isinstance(project_id, str):
        project_id = project_id.strip() or None
    if project_id:
        pid_key = _coerce_project_id(project_id)
        if pid_key is None:
            return jsonify({"error": "projectId must be a string"}), 400
        # update existing (ensure ownership)
        existing = mongo.db.projects.find_one({'_id': pid_key})
        if existing:
            if existing.get('user_id') != str(current_user['_id']):
                return jsonify({"error": "Project not found or unauthorized"}), 404
            mongo.db.projects.update_one({'_id': pid_key}, {'$set': doc})
            pid = pid_key
        else:
            doc['created_at'] = datetime.datetime.utcnow()
            doc['_id'] = pid_key
            res = mongo.db.projects.insert_one(doc)
            pid = res.inserted_id
    else:
        doc['created_at'] = datetime.datetime.utcnow()
        res = mongo.db.projects.insert_one(doc)
        pid = res.inserted_id

    return jsonify({
        'projectId': str(pid),
        'videoDirectory': video_directory,
        'selectedVideos': selected_videos,
        'fps': int(fps),
        'classes': classes,
        'attributes': attributes,
        'attributeDescriptions': attribute_descriptions,
    })

@app.route('/api/projects', methods=['GET'])
@token_required
def list_projects(current_user):
    """List all projects owned by the current user, newest first."""
    user_id = str(current_user['_id'])
    cursor = mongo.db.projects.find({'user_id': user_id}).sort('updated_at', -1)
    items = []
    for p in cursor:
        items.append({
            'projectId': str(p.get('_id')),
            'videoDirectory': p.get('video_directory'),
            'selectedVideos': p.get('selected_videos') or [],
            'fps': int(p.get('fps') or 1),
            'classes': p.get('classes') or [],
            'attributes': p.get('attributes') or {},
            'attributeDescriptions': p.get('attribute_descriptions') or {},
            'createdAt': p.get('created_at').isoformat() if p.get('created_at') else None,
            'updatedAt': p.get('updated_at').isoformat() if p.get('updated_at') else None,
        })
    return jsonify(items)


@app.route('/api/projects/<project_id>', methods=['GET'])
@token_required
def get_project(current_user, project_id):
    """Return a single project the user owns, including attributes and classes."""
    pid_key = _coerce_project_id(project_id)
    project = mongo.db.projects.find_one({'_id': pid_key}) if pid_key is not None else None
    if not project or project.get('user_id') != str(current_user['_id']):
        return jsonify({"error": "Project not found or unauthorized"}), 404

    return jsonify({
        'projectId': str(project['_id']),
        'videoDirectory': project.get('video_directory'),
        'selectedVideos': project.get('selected_videos') or [],
        'fps': int(project.get('fps') or 1),
        'classes': project.get('classes') or [],
        'attributes': project.get('attributes') or {},
        'attributeDescriptions': project.get('attribute_descriptions') or {},
        'createdAt': project.get('created_at').isoformat() if project.get('created_at') else None,
        'updatedAt': project.get('updated_at').isoformat() if project.get('updated_at') else None,
    })


@app.route('/api/projects/<project_id>', methods=['DELETE'])
@token_required
def delete_project(current_user, project_id):
    """Delete a project and all related annotations owned by the current user."""
    pid_key = _coerce_project_id(project_id)
    project = mongo.db.projects.find_one({'_id': pid_key}) if pid_key is not None else None
    if not project or project.get('user_id') != str(current_user['_id']):
        return jsonify({"error": "Project not found or unauthorized"}), 404

    # Delete related annotations first
    ann_res = mongo.db.annotations.delete_many({
        'user_id': str(current_user['_id']),
        'project_id': str(project['_id'])
    })
    # Delete the project
    proj_res = mongo.db.projects.delete_one({'_id': project['_id']})

    return jsonify({
        'success': True,
        'deleted': {
            'project': proj_res.deleted_count,
            'annotations': ann_res.deleted_count,
        }
    })


@app.route('/api/projects/<project_id>/export', methods=['GET'])
@token_required
def export_project_annotations(current_user, project_id):
    """Export project metadata and all annotations for this user/project as JSON."""
    pid_key = _coerce_project_id(project_id)
    project = mongo.db.projects.find_one({'_id': pid_key}) if pid_key is not None else None
    if not project or project.get('user_id') != str(current_user['_id']):
        return jsonify({"error": "Project not found or unauthorized"}), 404

    user_info = {
        'id': str(current_user['_id']),
        'username': current_user.get('username'),
    }

    # Gather annotations
    cursor = mongo.db.annotations.find({
        'user_id': str(current_user['_id']),
        'project_id': str(project['_id'])
    }).sort([('video_index', 1), ('sample_index', 1)])
    annotations = []
    for doc in cursor:
        annotations.append({
            'video_index': int(doc.get('video_index', 0)),
            'sample_index': int(doc.get('sample_index', 0)),
            'boxes': doc.get('boxes') or [],
            'updated_at': doc.get('updated_at').isoformat() if doc.get('updated_at') else None,
            'created_at': doc.get('created_at').isoformat() if doc.get('created_at') else None,
        })

    payload = {
        'schema_version': 1,
        'exported_at': datetime.datetime.utcnow().isoformat() + 'Z',
        'project': {
            'id': str(project['_id']),
            'video_directory': project.get('video_directory'),
            'selected_videos': project.get('selected_videos') or [],
            'fps': int(project.get('fps') or 1),
            'classes': project.get('classes') or [],
            'attributes': project.get('attributes') or {},
            'attributeDescriptions': project.get('attribute_descriptions') or {},
        },
        'user': user_info,
        'annotations': annotations,
    }

    data = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
    filename = f"annotations_{str(project['_id'])}.json"
    return Response(data, mimetype='application/json', headers={
        'Content-Disposition': f'attachment; filename="{filename}"'
    })


@app.route('/api/projects/<project_id>/rename', methods=['POST'])
@token_required
def rename_project(current_user, project_id):
    data = request.get_json(silent=True) or {}
    new_project_id = data.get('newProjectId')
    if not isinstance(new_project_id, str) or not new_project_id.strip():
        return jsonify({"error": "newProjectId is required"}), 400
    new_project_id = new_project_id.strip()

    old_key = _coerce_project_id(project_id)
    if old_key is None:
        return jsonify({"error": "Project not found or unauthorized"}), 404

    project = mongo.db.projects.find_one({'_id': old_key})
    if not project or project.get('user_id') != str(current_user['_id']):
        return jsonify({"error": "Project not found or unauthorized"}), 404

    new_key = _coerce_project_id(new_project_id)
    if new_key is None:
        return jsonify({"error": "newProjectId must be a string"}), 400

    if str(project.get('_id')) == str(new_key):
        return jsonify({"error": "newProjectId is the same as current"}), 400

    if mongo.db.projects.find_one({'_id': new_key}):
        return jsonify({"error": "Project ID already exists"}), 409

    new_doc = dict(project)
    new_doc['_id'] = new_key
    new_doc['updated_at'] = datetime.datetime.utcnow()
    mongo.db.projects.insert_one(new_doc)

    old_id_str = str(project.get('_id'))
    new_id_str = str(new_key)
    mongo.db.annotations.update_many(
        {
            'user_id': str(current_user['_id']),
            'project_id': old_id_str
        },
        {
            '$set': {
                'project_id': new_id_str,
                'updated_at': datetime.datetime.utcnow(),
            }
        }
    )

    mongo.db.projects.delete_one({'_id': project['_id']})

    return jsonify({
        'projectId': new_id_str,
        'videoDirectory': new_doc.get('video_directory'),
        'selectedVideos': new_doc.get('selected_videos') or [],
        'fps': int(new_doc.get('fps') or 1),
        'classes': new_doc.get('classes') or [],
        'attributes': new_doc.get('attributes') or {},
        'attributeDescriptions': new_doc.get('attribute_descriptions') or {},
    })


@app.route('/api/projects/<project_id>/import', methods=['POST'])
@token_required
def import_project_annotations(current_user, project_id):
    """Import annotations JSON for this project. Optionally updates classes/attributes."""
    pid_key = _coerce_project_id(project_id)
    project = mongo.db.projects.find_one({'_id': pid_key}) if pid_key is not None else None
    if not project or project.get('user_id') != str(current_user['_id']):
        return jsonify({"error": "Project not found or unauthorized"}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Body must be JSON object payload produced by export"}), 400

    proj_meta = data.get('project') or {}
    annos = data.get('annotations') or []

    # Optionally update classes/attributes/attribute descriptions if present
    updates = {}
    if isinstance(proj_meta.get('classes'), list):
        updates['classes'] = proj_meta['classes']
    attrs = _sanitize_attributes(proj_meta.get('attributes') or {})
    if attrs:
        updates['attributes'] = attrs
    raw_descriptions = proj_meta.get('attributeDescriptions')
    if raw_descriptions is None:
        raw_descriptions = proj_meta.get('attribute_descriptions')
    descriptions_source = attrs if attrs else (project.get('attributes') or {})
    descriptions = _sanitize_attribute_descriptions(raw_descriptions or {}, descriptions_source)
    if descriptions:
        updates['attribute_descriptions'] = descriptions
    if updates:
        updates['updated_at'] = datetime.datetime.utcnow()
        mongo.db.projects.update_one({'_id': project['_id']}, {'$set': updates})

    # Upsert annotations
    count = 0
    for item in annos:
        try:
            vi = int(item.get('video_index'))
            si = int(item.get('sample_index'))
        except Exception:
            continue
        boxes = item.get('boxes')
        if not isinstance(boxes, list):
            continue
        mongo.db.annotations.update_one(
            {
                'user_id': str(current_user['_id']),
                'project_id': str(project['_id']),
                'video_index': vi,
                'sample_index': si,
            },
            {
                '$set': {
                    'boxes': boxes,
                    'updated_at': datetime.datetime.utcnow(),
                },
                '$setOnInsert': {
                    'created_at': datetime.datetime.utcnow(),
                }
            },
            upsert=True
        )
        count += 1

    return jsonify({"success": True, "imported": count})


@app.route('/api/projects/import', methods=['POST'])
@token_required
def import_full_project(current_user):
    """Create a new project for the current user from an export JSON and import its annotations.

    Accepts the same payload produced by /export. Creates a project owned by the caller
    using metadata (video_directory, selected_videos, fps, classes, attributes), then upserts
    all provided annotations to this new project.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Body must be JSON object payload produced by export"}), 400

    proj_meta = payload.get('project') or {}
    video_directory = proj_meta.get('video_directory')
    selected_videos = proj_meta.get('selected_videos') or []
    fps = proj_meta.get('fps') or 1
    classes = proj_meta.get('classes') or []
    attributes_in = proj_meta.get('attributes') or {}
    attribute_descriptions_in = proj_meta.get('attributeDescriptions')
    if attribute_descriptions_in is None:
        attribute_descriptions_in = proj_meta.get('attribute_descriptions')

    # sanitize
    if not isinstance(selected_videos, list):
        selected_videos = []
    if not isinstance(classes, list):
        classes = []
    attributes = _sanitize_attributes(attributes_in)
    attribute_descriptions = _sanitize_attribute_descriptions(attribute_descriptions_in or {}, attributes)

    doc = {
        'user_id': str(current_user['_id']),
        'video_directory': video_directory,
        'selected_videos': selected_videos,
        'fps': int(fps) if isinstance(fps, (int, float, str)) else 1,
        'classes': classes,
        'attributes': attributes,
        'attribute_descriptions': attribute_descriptions,
        'created_at': datetime.datetime.utcnow(),
        'updated_at': datetime.datetime.utcnow(),
    }
    res = mongo.db.projects.insert_one(doc)
    new_pid = res.inserted_id

    # import annotations
    annos = payload.get('annotations') or []
    imported = 0
    for item in annos:
        try:
            vi = int(item.get('video_index'))
            si = int(item.get('sample_index'))
        except Exception:
            continue
        boxes = item.get('boxes')
        if not isinstance(boxes, list):
            continue
        mongo.db.annotations.update_one(
            {
                'user_id': str(current_user['_id']),
                'project_id': str(new_pid),
                'video_index': vi,
                'sample_index': si,
            },
            {
                '$set': {
                    'boxes': boxes,
                    'updated_at': datetime.datetime.utcnow(),
                },
                '$setOnInsert': {
                    'created_at': datetime.datetime.utcnow(),
                }
            },
            upsert=True
        )
        imported += 1

    return jsonify({
        'success': True,
        'projectId': str(new_pid),
        'videoDirectory': video_directory,
        'selectedVideos': selected_videos,
        'fps': int(doc['fps']),
        'classes': classes,
        'attributes': attributes,
        'attributeDescriptions': attribute_descriptions,
        'imported': imported,
    })


def _safe_video_path(base_dir, filename):
    # join and normalize to avoid traversal
    path = os.path.normpath(os.path.join(base_dir, filename))
    # basic safety: ensure path starts with base_dir
    base_dir_norm = os.path.normpath(base_dir)
    if not path.startswith(base_dir_norm):
        return None
    return path


def _video_info_for(project, video_index):
    videos = project.get('selected_videos') or []
    if video_index < 0 or video_index >= len(videos):
        return None, ("Invalid video_index", 400)

    video_path = _safe_video_path(project['video_directory'], videos[video_index])
    if not video_path or not os.path.isfile(video_path):
        return None, ("Video not found on server", 404)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None, ("Failed to open video", 500)

    raw_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()

    target_fps = int(project.get('fps') or 1)
    target_fps = max(1, target_fps)
    raw_fps = max(1.0, float(raw_fps))
    step = max(1, int(round(raw_fps / float(target_fps))))
    sampled_count = 0
    if total_frames > 0:
        sampled_count = int(math.floor((total_frames - 1) / step) + 1)

    return {
        'video_path': video_path,
        'raw_fps': raw_fps,
        'total_frames': total_frames,
        'target_fps': target_fps,
        'step': step,
        'sampled_count': sampled_count,
    }, None


@app.route('/api/projects/<project_id>/video_info', methods=['GET'])
@token_required
def get_video_info(current_user, project_id):
    pid_key = _coerce_project_id(project_id)
    project = mongo.db.projects.find_one({'_id': pid_key}) if pid_key is not None else None
    if not project or project.get('user_id') != str(current_user['_id']):
        return jsonify({"error": "Project not found or unauthorized"}), 404

    vi = request.args.get('video_index', default=0, type=int)
    info, err = _video_info_for(project, vi)
    if err:
        msg, code = err
        return jsonify({"error": msg}), code

    return jsonify({
        'raw_fps': info['raw_fps'],
        'total_frames': info['total_frames'],
        'target_fps': info['target_fps'],
        'step': info['step'],
        'sampled_count': info['sampled_count']
    })


@app.route('/api/projects/<project_id>/frame', methods=['GET'])
@token_required
def get_frame(current_user, project_id):
    pid_key = _coerce_project_id(project_id)
    project = mongo.db.projects.find_one({'_id': pid_key}) if pid_key is not None else None
    if not project or project.get('user_id') != str(current_user['_id']):
        return jsonify({"error": "Project not found or unauthorized"}), 404

    video_index = request.args.get('video_index', default=0, type=int)
    sample_index = request.args.get('sample_index', default=0, type=int)

    info, err = _video_info_for(project, video_index)
    if err:
        msg, code = err
        return jsonify({"error": msg}), code

    step = info['step']
    total_frames = info['total_frames']
    frame_num = min(sample_index * step, max(0, total_frames - 1))

    cap = cv2.VideoCapture(info['video_path'])
    if not cap.isOpened():
        return jsonify({"error": "Failed to open video"}), 500

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return jsonify({"error": "Failed to read frame"}), 500

    ok, buf = cv2.imencode('.jpg', frame)
    if not ok:
        return jsonify({"error": "Failed to encode frame"}), 500

    data = buf.tobytes()
    return Response(data, mimetype='image/jpeg', headers={
        'X-Frame-Step': str(step),
        'X-Sampled-Count': str(info['sampled_count'])
    })


# -------- Per-frame Annotations (project/video/sample specific) --------

@app.route('/api/projects/<project_id>/annotations', methods=['GET'])
@token_required
def get_frame_annotations(current_user, project_id):
    pid_key = _coerce_project_id(project_id)
    project = mongo.db.projects.find_one({'_id': pid_key}) if pid_key is not None else None
    if not project or project.get('user_id') != str(current_user['_id']):
        return jsonify({"error": "Project not found or unauthorized"}), 404

    video_index = request.args.get('video_index', type=int)
    sample_index = request.args.get('sample_index', type=int)
    if video_index is None or sample_index is None:
        return jsonify({"error": "video_index and sample_index are required"}), 400

    doc = mongo.db.annotations.find_one({
        'user_id': str(current_user['_id']),
        'project_id': str(project['_id']),
        'video_index': int(video_index),
        'sample_index': int(sample_index),
    })
    boxes = doc.get('boxes') if doc else []
    return jsonify(boxes)


@app.route('/api/projects/<project_id>/annotations', methods=['POST'])
@token_required
def save_frame_annotations(current_user, project_id):
    pid_key = _coerce_project_id(project_id)
    project = mongo.db.projects.find_one({'_id': pid_key}) if pid_key is not None else None
    if not project or project.get('user_id') != str(current_user['_id']):
        return jsonify({"error": "Project not found or unauthorized"}), 404

    video_index = request.args.get('video_index', type=int)
    sample_index = request.args.get('sample_index', type=int)
    if video_index is None or sample_index is None:
        return jsonify({"error": "video_index and sample_index are required"}), 400

    boxes = request.get_json(silent=True)
    if boxes is None or not isinstance(boxes, list):
        return jsonify({"error": "Body must be a JSON array of boxes"}), 400

    mongo.db.annotations.update_one(
        {
            'user_id': str(current_user['_id']),
            'project_id': str(project['_id']),
            'video_index': int(video_index),
            'sample_index': int(sample_index),
        },
        {
            '$set': {
                'boxes': boxes,
                'updated_at': datetime.datetime.utcnow(),
            },
            '$setOnInsert': {
                'created_at': datetime.datetime.utcnow(),
            }
        },
        upsert=True
    )

    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=56250, debug=True)
