


from flask import Flask, request, jsonify, Response
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

app = Flask(__name__)
CORS(app)

# Configure MongoDB connection (replace with your actual MongoDB URI)
app.config['MONGO_URI'] = 'mongodb://localhost:27017/labelmv'
mongo = PyMongo(app)

# Secret key for JWT
app.config['SECRET_KEY'] = 'your_secret_key_here'

# In-memory storage for annotations (for simplicity, will be replaced with database)
annotations_storage = {}

@app.route('/videos', methods=['GET'])
def get_videos():
    directory = request.args.get('directory')
    if not directory:
        return jsonify({"error": "Directory parameter is required"}), 400

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
    project_id = data.get('projectId')  # optional for update

    if not video_directory or not isinstance(selected_videos, list) or not fps:
        return jsonify({"error": "videoDirectory, selected_videos and fps are required"}), 400
    if not isinstance(classes, list):
        return jsonify({"error": "classes must be a list"}), 400
    # validate attributes shape if provided
    attributes = {}
    if isinstance(raw_attributes, dict):
        for k, v in raw_attributes.items():
            if not isinstance(k, str):
                continue
            if isinstance(v, list):
                opts = [str(x) for x in v if isinstance(x, (str, int, float))]
                if opts:
                    attributes[k] = opts

    doc = {
        'user_id': str(current_user['_id']),
        'video_directory': video_directory,
        'selected_videos': selected_videos,
        'fps': int(fps),
        'classes': classes,
        'attributes': attributes,
        'updated_at': datetime.datetime.utcnow(),
    }

    if project_id:
        # update existing (ensure ownership)
        existing = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
        if not existing or existing.get('user_id') != str(current_user['_id']):
            return jsonify({"error": "Project not found or unauthorized"}), 404
        mongo.db.projects.update_one({'_id': ObjectId(project_id)}, {'$set': doc})
        pid = ObjectId(project_id)
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
        'attributes': attributes
    })


@app.route('/api/projects/<project_id>', methods=['GET'])
@token_required
def get_project(current_user, project_id):
    """Return a single project the user owns, including attributes and classes."""
    try:
        project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
    except Exception:
        project = None
    if not project or project.get('user_id') != str(current_user['_id']):
        return jsonify({"error": "Project not found or unauthorized"}), 404

    return jsonify({
        'projectId': str(project['_id']),
        'videoDirectory': project.get('video_directory'),
        'selectedVideos': project.get('selected_videos') or [],
        'fps': int(project.get('fps') or 1),
        'classes': project.get('classes') or [],
        'attributes': project.get('attributes') or {},
        'createdAt': project.get('created_at').isoformat() if project.get('created_at') else None,
        'updatedAt': project.get('updated_at').isoformat() if project.get('updated_at') else None,
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
    try:
        project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
    except Exception:
        project = None
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
    try:
        project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
    except Exception:
        project = None
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
    try:
        project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
    except Exception:
        project = None
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
    try:
        project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
    except Exception:
        project = None
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
