from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_pymongo import PyMongo
from ollama import Client
from bson import ObjectId
import os
import json
import re
import jwt
import time
import datetime
import cv2
import math
import logging

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app.config['MONGO_URI'] = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/labelmv')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'changeme-in-prod')
mongo = PyMongo(app)

OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen3-vl:8b')
OLLAMA_HOST = os.environ.get('OLLAMA_HOST')
OLLAMA_TIMEOUT = float(os.environ.get('OLLAMA_TIMEOUT', '180'))

try:
    if OLLAMA_HOST:
        ollama_client = Client(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT)
    else:
        ollama_client = Client(timeout=OLLAMA_TIMEOUT)
except TypeError:
    ollama_client = Client(host=OLLAMA_HOST) if OLLAMA_HOST else Client()


def _coerce_project_id(project_id):
    if isinstance(project_id, ObjectId):
        return project_id
    if isinstance(project_id, str) and ObjectId.is_valid(project_id):
        return ObjectId(project_id)
    if isinstance(project_id, str):
        return project_id
    return None


def _safe_video_path(base_dir, filename):
    path = os.path.normpath(os.path.join(base_dir, filename))
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


def _decode_user_id(auth_header):
    if not auth_header or not auth_header.startswith('Bearer '):
        return None, "Token is missing"
    token = auth_header.split(' ', 1)[1]
    try:
        data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
    except Exception as exc:
        return None, f"Token is invalid: {exc}"
    user_id = data.get('user_id')
    if not user_id:
        return None, "Token missing user_id"
    return str(user_id), None


def _extract_json_array(text):
    if not text:
        return []
    cleaned = text.strip()
    if "```" in cleaned:
        cleaned = re.sub(r"```(?:json)?", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "")
    start = cleaned.find('[')
    end = cleaned.rfind(']')
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON array found in model response")
    snippet = cleaned[start:end + 1]
    return json.loads(snippet)


def _normalize_detections(raw):
    detections = []
    if isinstance(raw, dict) and isinstance(raw.get('boxes'), list):
        raw = raw['boxes']
    if not isinstance(raw, list):
        return detections
    for item in raw:
        if not isinstance(item, dict):
            continue
        bbox = item.get('bbox_2d')
        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            continue
        try:
            x1, y1, x2, y2 = [float(v) for v in bbox]
        except (TypeError, ValueError):
            continue
        label = item.get('label')
        if label is None:
            label = ""
        detections.append({
            'bbox_2d': [x1, y1, x2, y2],
            'label': str(label).strip(),
        })
    return detections


def _bbox_to_norm(bbox, img_w, img_h):
    x1, y1, x2, y2 = bbox
    max_val = max(abs(x1), abs(y1), abs(x2), abs(y2))
    if max_val <= 1.0:
        scale_x = 1.0
        scale_y = 1.0
    elif max_val <= 1000.0:
        scale_x = 1000.0
        scale_y = 1000.0
    else:
        scale_x = float(max(1, img_w))
        scale_y = float(max(1, img_h))

    left = min(x1, x2) / scale_x
    right = max(x1, x2) / scale_x
    top = min(y1, y2) / scale_y
    bottom = max(y1, y2) / scale_y

    width = max(0.0, right - left)
    height = max(0.0, bottom - top)

    min_norm = 0.001
    width = max(min_norm, width)
    height = max(min_norm, height)

    left = min(max(0.0, left), 1.0 - width)
    top = min(max(0.0, top), 1.0 - height)

    return left, top, width, height


def _default_attributes(attributes):
    if not isinstance(attributes, dict):
        return {}
    return {name: "" for name in attributes.keys()}


@app.route('/agent/detect', methods=['POST'])
def detect_objects():
    user_id, err = _decode_user_id(request.headers.get('Authorization'))
    if err:
        return jsonify({"error": err}), 403

    payload = request.get_json(silent=True) or {}
    project_id = payload.get('projectId')
    video_index = payload.get('videoIndex')
    sample_index = payload.get('sampleIndex')
    label = (payload.get('label') or '').strip()

    if project_id is None or video_index is None or sample_index is None:
        return jsonify({"error": "projectId, videoIndex, and sampleIndex are required"}), 400
    if not label:
        return jsonify({"error": "label is required"}), 400

    logger.info(
        "Detect request label=%s project_id=%s video_index=%s sample_index=%s",
        label, project_id, video_index, sample_index
    )

    pid_key = _coerce_project_id(project_id)
    project = mongo.db.projects.find_one({'_id': pid_key}) if pid_key is not None else None
    if not project or project.get('user_id') != user_id:
        return jsonify({"error": "Project not found or unauthorized"}), 404

    try:
        video_index = int(video_index)
        sample_index = int(sample_index)
    except (TypeError, ValueError):
        return jsonify({"error": "videoIndex and sampleIndex must be integers"}), 400

    info, info_err = _video_info_for(project, video_index)
    if info_err:
        msg, code = info_err
        return jsonify({"error": msg}), code

    frame_num = min(sample_index * info['step'], max(0, info['total_frames'] - 1))
    cap = cv2.VideoCapture(info['video_path'])
    if not cap.isOpened():
        return jsonify({"error": "Failed to open video"}), 500
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return jsonify({"error": "Failed to read frame"}), 500

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    ok, buf = cv2.imencode('.png', frame_rgb)
    if not ok:
        return jsonify({"error": "Failed to encode frame"}), 500

    prompt = (
        f"Localize {label} object in the image into a json format. "
        "Return only a JSON array like:\n"
        "[\n"
        "\t{\"bbox_2d\": [x1, y1, x2, y2], \"label\": \"object_name\"},\n"
        "]"
    )
    try:
        response = ollama_client.chat(
            model=OLLAMA_MODEL,
            messages=[{
                "role": "user",
                "content": prompt,
                "images": [buf.tobytes()],
            }],
        )
    except Exception as exc:
        return jsonify({"error": f"Ollama request failed: {exc}"}), 502
    if isinstance(response, dict):
        model_text = response.get('message', {}).get('content', '')
    else:
        message = getattr(response, 'message', None)
        if isinstance(message, dict):
            model_text = message.get('content', '')
        else:
            model_text = getattr(message, 'content', '') if message is not None else ''

    logger.info("Ollama raw response (truncated): %s", (model_text or "")[:500])

    try:
        raw_json = _extract_json_array(model_text)
    except (ValueError, json.JSONDecodeError) as exc:
        return jsonify({
            "error": f"Failed to parse model response: {exc}",
            "raw": model_text
        }), 502

    detections = _normalize_detections(raw_json)
    img_h, img_w = frame.shape[:2]
    attrs_default = _default_attributes(project.get('attributes') or {})
    base_id = int(time.time() * 1000)
    boxes = []
    for idx, det in enumerate(detections):
        bbox = det['bbox_2d']
        left, top, width, height = _bbox_to_norm(bbox, img_w, img_h)
        class_name = det.get('label') or label
        boxes.append({
            "id": base_id + idx,
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "className": class_name,
            "objectId": 0,
            "attributes": dict(attrs_default),
        })

    mongo.db.annotations.update_one(
        {
            'user_id': user_id,
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

    return jsonify({
        "boxes": boxes,
        "detections": detections,
        "raw": model_text,
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=56260, debug=True)
