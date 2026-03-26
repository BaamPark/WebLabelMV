
from flask import Flask, request, jsonify, Response, stream_with_context
from flask import send_file
from flask_cors import CORS
import os
import secrets
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
import numpy as np

from agent_prompting import (
    build_contextual_chat_prompt,
    build_turn_user_message,
    extract_action_json,
    log_agent_messages,
    select_box_subset,
    serialize_boxes_for_prompt,
    strip_action_json,
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


def _is_valid_box_id(value):
    if isinstance(value, bool):
        return False
    return isinstance(value, (str, int, float))


def _coerce_box_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _box_to_agent_coords(box):
    left = float(box.get('left', 0))
    top = float(box.get('top', 0))
    width = float(box.get('width', 0))
    height = float(box.get('height', 0))
    x1 = round(left * 1000, 3)
    y1 = round(top * 1000, 3)
    x2 = round((left + width) * 1000, 3)
    y2 = round((top + height) * 1000, 3)
    return x1, y1, x2, y2


def _agent_bbox_to_backend_box(bbox_1000):
    if not isinstance(bbox_1000, list) or len(bbox_1000) != 4:
        return None, "bbox_1000 must be an array of four numbers: [x1, y1, x2, y2]"

    coords = []
    for value in bbox_1000:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None, "bbox_1000 must contain only finite numbers"
        coords.append(float(value))

    x1, y1, x2, y2 = coords
    if x1 < 0 or y1 < 0:
        return None, f"x1,y1 value ({x1}, {y1}) exceeds the frame range; agent bbox coordinates must stay within [0, 1000]"
    if x2 > 1000:
        return None, f"x2 value {x2} exceeds the frame width; agent bbox coordinates must stay within [0, 1000]"
    if y2 > 1000:
        return None, f"y2 value {y2} exceeds the frame height; agent bbox coordinates must stay within [0, 1000]"
    if x2 <= x1:
        return None, (
            f"x2 must be greater than x1 and remain inside the frame; "
            f"current bbox is [x1, y1, x2, y2] = [{x1}, {y1}, {x2}, {y2}]"
        )
    if y2 <= y1:
        return None, (
            f"y2 must be greater than y1 and remain inside the frame; "
            f"current bbox is [x1, y1, x2, y2] = [{x1}, {y1}, {x2}, {y2}]"
        )

    return {
        'left': x1 / 1000.0,
        'top': y1 / 1000.0,
        'width': (x2 - x1) / 1000.0,
        'height': (y2 - y1) / 1000.0,
    }, None


def _normalize_and_validate_boxes(boxes, project):
    project_classes = [item for item in (project.get('classes') or []) if isinstance(item, str)]
    project_attributes = project.get('attributes') or {}
    normalized_boxes = []

    for index, box in enumerate(boxes):
        if not isinstance(box, dict):
            return None, f"Invalid box at index {index}: each box must be a JSON object"

        box_id = box.get('boxId')
        if box_id in (None, ''):
            box_id = box.get('id')
        if not _is_valid_box_id(box_id):
            return None, f"Invalid box at index {index}: id is required and must be a string or number"

        left = _coerce_box_number(box.get('left'))
        top = _coerce_box_number(box.get('top'))
        width = _coerce_box_number(box.get('width'))
        height = _coerce_box_number(box.get('height'))
        if left is None or top is None or width is None or height is None:
            return None, (
                f"Invalid box at index {index}: bbox must define finite backend coordinates "
                f"(left, top, width, height) so it can be converted to agent coordinates [x1, y1, x2, y2]"
            )
        x1, y1, x2, y2 = _box_to_agent_coords({
            'left': left,
            'top': top,
            'width': width,
            'height': height,
        })
        if left < 0 or left > 1:
            return None, (
                f"Invalid box at index {index}: x1,y1 value ({x1}, {y1}) exceeds the frame range; "
                f"agent bbox coordinates must stay within [0, 1000]"
            )
        if top < 0 or top > 1:
            return None, (
                f"Invalid box at index {index}: x1,y1 value ({x1}, {y1}) exceeds the frame range; "
                f"agent bbox coordinates must stay within [0, 1000]"
            )
        if width <= 0 or width > 1:
            return None, (
                f"Invalid box at index {index}: x2 must be greater than x1 and remain inside the frame; "
                f"current bbox maps to [x1, y1, x2, y2] = [{x1}, {y1}, {x2}, {y2}]"
            )
        if height <= 0 or height > 1:
            return None, (
                f"Invalid box at index {index}: y2 must be greater than y1 and remain inside the frame; "
                f"current bbox maps to [x1, y1, x2, y2] = [{x1}, {y1}, {x2}, {y2}]"
            )
        if left + width > 1:
            return None, (
                f"Invalid box at index {index}: x2 value {x2} exceeds the frame width; "
                f"agent bbox coordinates must stay within [0, 1000]"
            )
        if top + height > 1:
            return None, (
                f"Invalid box at index {index}: y2 value {y2} exceeds the frame height; "
                f"agent bbox coordinates must stay within [0, 1000]"
            )

        class_name = box.get('className')
        if not isinstance(class_name, str) or not class_name.strip():
            return None, f"Invalid box at index {index}: className is required"
        class_name = class_name.strip()
        if project_classes and class_name not in project_classes:
            return None, f"Invalid box at index {index}: className '{class_name}' is not in project classes"

        object_id_raw = box.get('objectId')
        if object_id_raw is None:
            has_new_schema_box_id = box.get('boxId') not in (None, '')
            object_id_raw = box.get('id', 0) if has_new_schema_box_id else 0
        try:
            object_id = int(object_id_raw)
        except (TypeError, ValueError):
            return None, f"Invalid box at index {index}: objectId must be an integer"
        if object_id < 0:
            return None, f"Invalid box at index {index}: objectId must be greater than or equal to 0"

        raw_attributes = box.get('attributes')
        if raw_attributes is None:
            raw_attributes = {}
        if not isinstance(raw_attributes, dict):
            return None, f"Invalid box at index {index}: attributes must be a JSON object"

        unknown_attrs = sorted(key for key in raw_attributes.keys() if key not in project_attributes)
        if unknown_attrs:
            return None, (
                f"Invalid box at index {index}: unknown attribute name(s): "
                + ", ".join(repr(name) for name in unknown_attrs)
            )

        normalized_attributes = {}
        for attr_name, valid_values in project_attributes.items():
            raw_value = raw_attributes.get(attr_name, '')
            if raw_value is None:
                raw_value = ''
            if not isinstance(raw_value, str):
                return None, f"Invalid box at index {index}: attribute '{attr_name}' must be a string"
            if raw_value and raw_value not in valid_values:
                return None, (
                    f"Invalid box at index {index}: attribute '{attr_name}' has unsupported value "
                    f"'{raw_value}'"
                )
            normalized_attributes[attr_name] = raw_value

        normalized_boxes.append({
            'id': box_id,
            'left': left,
            'top': top,
            'width': width,
            'height': height,
            'className': class_name,
            'objectId': object_id,
            'attributes': normalized_attributes,
        })

    return normalized_boxes, None


def _normalize_box_shape_for_app(box):
    if not isinstance(box, dict):
        return box
    internal_id = box.get('boxId')
    if internal_id in (None, ''):
        internal_id = box.get('id')
    user_id = box.get('objectId')
    if user_id is None and box.get('boxId') not in (None, ''):
        user_id = box.get('id')
    return {
        **box,
        'id': internal_id,
        'objectId': user_id,
    }


def _normalize_boxes_shape_for_app(boxes):
    if not isinstance(boxes, list):
        return []
    return [_normalize_box_shape_for_app(box) for box in boxes if isinstance(box, dict)]


def _normalize_box_shape_for_export(box):
    if not isinstance(box, dict):
        return box
    internal_id = box.get('boxId')
    if internal_id in (None, ''):
        internal_id = box.get('id')
    user_id = box.get('objectId')
    if user_id is None and box.get('boxId') not in (None, ''):
        user_id = box.get('id')
    exported = {
        **box,
        'boxId': internal_id,
        'id': user_id,
    }
    exported.pop('objectId', None)
    return exported


def _normalize_boxes_shape_for_export(boxes):
    if not isinstance(boxes, list):
        return []
    return [_normalize_box_shape_for_export(box) for box in boxes if isinstance(box, dict)]


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
    return _normalize_boxes_shape_for_app(boxes)


def _upsert_frame_annotations(user_id, project_id, video_index, sample_index, boxes):
    mongo.db.annotations.update_one(
        {
            'user_id': str(user_id),
            'project_id': str(project_id),
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


def _generate_box_id(existing_boxes):
    alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'
    existing_ids = {str(box.get('id')) for box in existing_boxes or []}
    while True:
        candidate = ''.join(secrets.choice(alphabet) for _ in range(6))
        if candidate not in existing_ids:
            return candidate


def _resolve_action_target(action_target_frame, source_video_index, source_sample_index,
                           target_scope, target_video_index, target_sample_index):
    if action_target_frame == 'target':
        if target_scope == 'none' or target_video_index is None or target_sample_index is None:
            return None, "target_frame='target' was requested, but no target frame is available in this chat session"
        return {
            'video_index': int(target_video_index),
            'sample_index': int(target_sample_index),
            'label': 'target frame',
        }, None

    return {
        'video_index': int(source_video_index),
        'sample_index': int(source_sample_index),
        'label': 'current frame',
    }, None


def _load_target_boxes(project, current_user, frame_target):
    return _get_annotation_boxes_for(
        current_user['_id'],
        project['_id'],
        frame_target['video_index'],
        frame_target['sample_index'],
    )


def _save_target_boxes(project, current_user, frame_target, boxes):
    normalized_boxes, validation_error = _normalize_and_validate_boxes(boxes, project)
    if validation_error:
        return None, validation_error

    _upsert_frame_annotations(
        current_user['_id'],
        project['_id'],
        frame_target['video_index'],
        frame_target['sample_index'],
        normalized_boxes,
    )
    return normalized_boxes, None


def _find_target_box(existing_boxes, box_id, action_name, frame_target):
    if box_id is None or str(box_id).strip() == '':
        return None, None, {
            'success': False,
            'message': f"{action_name} requires box_id",
        }

    target_box_index = next((index for index, box in enumerate(existing_boxes) if str(box.get('id')) == str(box_id)), None)
    if target_box_index is None:
        return None, None, {
            'success': False,
            'message': (
                f"{action_name} could not find box_id '{box_id}' in the {frame_target['label']} "
                f"(video_index={frame_target['video_index']}, sample_index={frame_target['sample_index']})"
            ),
        }
    return target_box_index, existing_boxes[target_box_index], None


def _execute_agent_action(action_payload, project, current_user, source_video_index, source_sample_index,
                          target_scope, target_video_index, target_sample_index):
    if not isinstance(action_payload, dict):
        return None, None

    action_name = (action_payload.get('action') or '').strip()
    if not action_name:
        return None, None

    target_frame = (action_payload.get('target_frame') or 'current').strip().lower()
    if target_frame not in {'current', 'target'}:
        return None, {
            'success': False,
            'message': f"{action_name} requires target_frame to be either 'current' or 'target'",
        }

    frame_target, target_error = _resolve_action_target(
        target_frame,
        source_video_index,
        source_sample_index,
        target_scope,
        target_video_index,
        target_sample_index,
    )
    if target_error:
        return None, {
            'success': False,
            'message': target_error,
        }

    existing_boxes = _load_target_boxes(project, current_user, frame_target)

    if action_name == 'create_box':
        requested_boxes = action_payload.get('boxes')
        if isinstance(requested_boxes, list):
            if not requested_boxes:
                return None, {
                    'success': False,
                    'message': "create_box boxes must be a non-empty array",
                }
            box_specs = requested_boxes
        else:
            box_specs = [{
                'className': action_payload.get('className'),
                'bbox_1000': action_payload.get('bbox_1000'),
            }]

        created_boxes = []
        next_boxes = list(existing_boxes)
        for item_index, box_spec in enumerate(box_specs):
            if not isinstance(box_spec, dict):
                return None, {
                    'success': False,
                    'message': f"create_box item {item_index} must be an object",
                }

            class_name = box_spec.get('className')
            if not isinstance(class_name, str) or not class_name.strip():
                return None, {
                    'success': False,
                    'message': f"create_box item {item_index} requires className",
                }
            class_name = class_name.strip()

            if class_name not in (project.get('classes') or []):
                return None, {
                    'success': False,
                    'message': f"create_box item {item_index} className '{class_name}' is not in project classes",
                }

            bbox_backend, bbox_error = _agent_bbox_to_backend_box(box_spec.get('bbox_1000'))
            if bbox_error:
                return None, {
                    'success': False,
                    'message': f"create_box item {item_index}: {bbox_error}",
                }

            new_box = {
                'id': _generate_box_id(next_boxes),
                'left': bbox_backend['left'],
                'top': bbox_backend['top'],
                'width': bbox_backend['width'],
                'height': bbox_backend['height'],
                'className': class_name,
                'objectId': 0,
                'attributes': {name: '' for name in (project.get('attributes') or {}).keys()},
            }
            created_boxes.append(new_box)
            next_boxes.append(new_box)

        _saved_boxes, validation_error = _save_target_boxes(project, current_user, frame_target, next_boxes)
        if validation_error:
            return None, {
                'success': False,
                'message': validation_error,
            }

        return {
            'action': 'create_box',
            'target_frame': target_frame,
            'video_index': frame_target['video_index'],
            'sample_index': frame_target['sample_index'],
            'box': created_boxes[0] if len(created_boxes) == 1 else None,
            'boxes': created_boxes,
        }, {
            'success': True,
            'message': (
                f"Created {len(created_boxes)} new box(es) in the {frame_target['label']} "
                f"(video_index={frame_target['video_index']}, sample_index={frame_target['sample_index']})"
            ),
            'action': 'create_box',
            'video_index': frame_target['video_index'],
            'sample_index': frame_target['sample_index'],
            'box_id': created_boxes[0]['id'] if len(created_boxes) == 1 else None,
            'box_ids': [box['id'] for box in created_boxes],
        }

    if action_name == 'update_box_geometry':
        box_id = action_payload.get('box_id')

        bbox_backend, bbox_error = _agent_bbox_to_backend_box(action_payload.get('bbox_1000'))
        if bbox_error:
            return None, {
                'success': False,
                'message': bbox_error,
            }

        target_box_index, target_box, target_box_error = _find_target_box(
            existing_boxes,
            box_id,
            'update_box_geometry',
            frame_target,
        )
        if target_box_error:
            return None, target_box_error

        updated_box = {
            **target_box,
            'left': bbox_backend['left'],
            'top': bbox_backend['top'],
            'width': bbox_backend['width'],
            'height': bbox_backend['height'],
        }
        next_boxes = list(existing_boxes)
        next_boxes[target_box_index] = updated_box
        _saved_boxes, validation_error = _save_target_boxes(project, current_user, frame_target, next_boxes)
        if validation_error:
            return None, {
                'success': False,
                'message': validation_error,
            }

        return {
            'action': 'update_box_geometry',
            'target_frame': target_frame,
            'video_index': frame_target['video_index'],
            'sample_index': frame_target['sample_index'],
            'box': updated_box,
        }, {
            'success': True,
            'message': (
                f"Updated box geometry for box_id={box_id} in the {frame_target['label']} "
                f"(video_index={frame_target['video_index']}, sample_index={frame_target['sample_index']})"
            ),
            'action': 'update_box_geometry',
            'video_index': frame_target['video_index'],
            'sample_index': frame_target['sample_index'],
            'box_id': updated_box['id'],
        }

    if action_name == 'update_box_class':
        box_id = action_payload.get('box_id')
        class_name = action_payload.get('className')
        if not isinstance(class_name, str) or not class_name.strip():
            return None, {
                'success': False,
                'message': "update_box_class requires className",
            }
        class_name = class_name.strip()
        if class_name not in (project.get('classes') or []):
            return None, {
                'success': False,
                'message': f"update_box_class className '{class_name}' is not in project classes",
            }

        target_box_index, target_box, target_box_error = _find_target_box(
            existing_boxes,
            box_id,
            'update_box_class',
            frame_target,
        )
        if target_box_error:
            return None, target_box_error

        updated_box = {
            **target_box,
            'className': class_name,
        }
        next_boxes = list(existing_boxes)
        next_boxes[target_box_index] = updated_box
        _saved_boxes, validation_error = _save_target_boxes(project, current_user, frame_target, next_boxes)
        if validation_error:
            return None, {
                'success': False,
                'message': validation_error,
            }

        return {
            'action': 'update_box_class',
            'target_frame': target_frame,
            'video_index': frame_target['video_index'],
            'sample_index': frame_target['sample_index'],
            'box': updated_box,
        }, {
            'success': True,
            'message': (
                f"Updated class for box_id={box_id} to '{class_name}' in the {frame_target['label']} "
                f"(video_index={frame_target['video_index']}, sample_index={frame_target['sample_index']})"
            ),
            'action': 'update_box_class',
            'video_index': frame_target['video_index'],
            'sample_index': frame_target['sample_index'],
            'box_id': updated_box['id'],
        }

    if action_name == 'update_box_attributes':
        box_id = action_payload.get('box_id')
        attributes_update = action_payload.get('attributes')
        if not isinstance(attributes_update, dict) or not attributes_update:
            return None, {
                'success': False,
                'message': "update_box_attributes requires a non-empty attributes object",
            }

        project_attributes = project.get('attributes') or {}
        normalized_updates = {}
        for attr_name, attr_value in attributes_update.items():
            if attr_name not in project_attributes:
                return None, {
                    'success': False,
                    'message': f"update_box_attributes unknown attribute name '{attr_name}'",
                }
            if attr_value is None:
                attr_value = ''
            if not isinstance(attr_value, str):
                return None, {
                    'success': False,
                    'message': f"update_box_attributes value for '{attr_name}' must be a string",
                }
            if attr_value and attr_value not in project_attributes[attr_name]:
                return None, {
                    'success': False,
                    'message': (
                        f"update_box_attributes value '{attr_value}' is not supported for attribute '{attr_name}'"
                    ),
                }
            normalized_updates[attr_name] = attr_value

        target_box_index, target_box, target_box_error = _find_target_box(
            existing_boxes,
            box_id,
            'update_box_attributes',
            frame_target,
        )
        if target_box_error:
            return None, target_box_error

        updated_box = {
            **target_box,
            'attributes': {
                **(target_box.get('attributes') or {}),
                **normalized_updates,
            },
        }
        next_boxes = list(existing_boxes)
        next_boxes[target_box_index] = updated_box
        _saved_boxes, validation_error = _save_target_boxes(project, current_user, frame_target, next_boxes)
        if validation_error:
            return None, {
                'success': False,
                'message': validation_error,
            }

        return {
            'action': 'update_box_attributes',
            'target_frame': target_frame,
            'video_index': frame_target['video_index'],
            'sample_index': frame_target['sample_index'],
            'box': updated_box,
        }, {
            'success': True,
            'message': (
                f"Updated attributes for box_id={box_id} in the {frame_target['label']} "
                f"(video_index={frame_target['video_index']}, sample_index={frame_target['sample_index']})"
            ),
            'action': 'update_box_attributes',
            'video_index': frame_target['video_index'],
            'sample_index': frame_target['sample_index'],
            'box_id': updated_box['id'],
        }

    if action_name == 'update_box_object_id':
        box_id = action_payload.get('box_id')
        object_id_raw = action_payload.get('objectId')
        try:
            object_id = int(object_id_raw)
        except (TypeError, ValueError):
            return None, {
                'success': False,
                'message': "update_box_object_id requires objectId to be an integer",
            }
        if object_id < 0:
            return None, {
                'success': False,
                'message': "update_box_object_id requires objectId to be greater than or equal to 0",
            }

        target_box_index, target_box, target_box_error = _find_target_box(
            existing_boxes,
            box_id,
            'update_box_object_id',
            frame_target,
        )
        if target_box_error:
            return None, target_box_error

        updated_box = {
            **target_box,
            'objectId': object_id,
        }
        next_boxes = list(existing_boxes)
        next_boxes[target_box_index] = updated_box
        _saved_boxes, validation_error = _save_target_boxes(project, current_user, frame_target, next_boxes)
        if validation_error:
            return None, {
                'success': False,
                'message': validation_error,
            }

        return {
            'action': 'update_box_object_id',
            'target_frame': target_frame,
            'video_index': frame_target['video_index'],
            'sample_index': frame_target['sample_index'],
            'box': updated_box,
        }, {
            'success': True,
            'message': (
                f"Updated objectId for box_id={box_id} to {object_id} in the {frame_target['label']} "
                f"(video_index={frame_target['video_index']}, sample_index={frame_target['sample_index']})"
            ),
            'action': 'update_box_object_id',
            'video_index': frame_target['video_index'],
            'sample_index': frame_target['sample_index'],
            'box_id': updated_box['id'],
        }

    if action_name == 'delete_box':
        box_id = action_payload.get('box_id')

        target_box_index, target_box, target_box_error = _find_target_box(
            existing_boxes,
            box_id,
            'delete_box',
            frame_target,
        )
        if target_box_error:
            return None, target_box_error

        next_boxes = list(existing_boxes)
        deleted_box = next_boxes.pop(target_box_index)
        _saved_boxes, validation_error = _save_target_boxes(project, current_user, frame_target, next_boxes)
        if validation_error:
            return None, {
                'success': False,
                'message': validation_error,
            }

        return {
            'action': 'delete_box',
            'target_frame': target_frame,
            'video_index': frame_target['video_index'],
            'sample_index': frame_target['sample_index'],
            'box': deleted_box,
        }, {
            'success': True,
            'message': (
                f"Deleted box_id={box_id} from the {frame_target['label']} "
                f"(video_index={frame_target['video_index']}, sample_index={frame_target['sample_index']})"
            ),
            'action': 'delete_box',
            'video_index': frame_target['video_index'],
            'sample_index': frame_target['sample_index'],
            'box_id': deleted_box['id'],
        }

    return None, {
        'success': False,
        'message': f"Unsupported action '{action_name}'",
    }


def _build_tool_result_message(action_payload, action_result):
    action_name = None
    if isinstance(action_payload, dict):
        action_name = action_payload.get('action')

    return json.dumps({
        'message_type': 'tool_result',
        'tool_name': action_name,
        'tool_result': action_result,
        'instruction': (
            'Use this tool result to continue solving the user request. '
            'If more tool use is needed, emit another ACTION_JSON. '
            'Otherwise, answer the user directly.'
        ),
    }, ensure_ascii=False)


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


def _render_current_frame_overlay(frame_bytes, boxes):
    image_array = cv2.imdecode(np.frombuffer(frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image_array is None:
        raise ChatbotServiceError("Failed to decode frame for overlay rendering", status_code=500)

    image_h, image_w = image_array.shape[:2]
    box_color = (0, 255, 0)
    text_color = (255, 255, 255)
    text_bg_color = (0, 0, 0)
    box_thickness = 3
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.65
    font_thickness = 2
    text_padding_x = 6
    text_padding_y = 5
    label_gap = 4

    for box in boxes or []:
        try:
            left = float(box.get('left', 0.0))
            top = float(box.get('top', 0.0))
            width = float(box.get('width', 0.0))
            height = float(box.get('height', 0.0))
        except (TypeError, ValueError):
            continue

        x1 = max(0, min(image_w - 1, int(round(left * image_w))))
        y1 = max(0, min(image_h - 1, int(round(top * image_h))))
        x2 = max(0, min(image_w - 1, int(round((left + width) * image_w))))
        y2 = max(0, min(image_h - 1, int(round((top + height) * image_h))))

        if x2 <= x1 or y2 <= y1:
            continue

        cv2.rectangle(image_array, (x1, y1), (x2, y2), box_color, box_thickness)

        object_id = box.get('objectId')
        if object_id is None:
            continue
        label_text = f"id={object_id}"
        (text_w, text_h), baseline = cv2.getTextSize(label_text, font, font_scale, font_thickness)
        rect_w = text_w + (text_padding_x * 2)
        rect_h = text_h + (text_padding_y * 2) + baseline
        rect_x2 = x2
        rect_x1 = max(0, rect_x2 - rect_w)
        rect_y2 = max(rect_h, y1 + rect_h + label_gap)
        rect_y1 = max(0, rect_y2 - rect_h)
        cv2.rectangle(image_array, (rect_x1, rect_y1), (rect_x2, rect_y2), text_bg_color, thickness=-1)
        text_x = rect_x1 + text_padding_x
        text_y = rect_y2 - baseline - text_padding_y
        cv2.putText(image_array, label_text, (text_x, text_y), font, font_scale, text_color, font_thickness, lineType=cv2.LINE_AA)

    ok, buf = cv2.imencode('.jpg', image_array)
    if not ok:
        raise ChatbotServiceError("Failed to encode overlaid frame", status_code=500)
    return buf.tobytes()


def _describe_image_relationship(target_scope, source_video_index, target_video_index, project):
    if target_scope == 'previous_current_view':
        return 'the previous frame from the current view'
    if target_scope == 'next_current_view':
        return 'the next frame from the current view'
    if isinstance(target_scope, str) and target_scope.startswith('view_'):
        selected_videos = project.get('selected_videos') or []
        target_name = (
            selected_videos[target_video_index]
            if isinstance(target_video_index, int) and 0 <= target_video_index < len(selected_videos)
            else None
        )
        if target_name:
            return f'the current frame from another view ({target_name})'
        return 'the current frame from another view'
    return None

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
        selected_box_value = item.get('selected_box')
        normalized_selected_box = None
        if isinstance(selected_box_value, dict):
            if 'bbox_1000' in selected_box_value and 'boxId' in selected_box_value:
                normalized_selected_box = selected_box_value
            else:
                serialized_selected_boxes = serialize_boxes_for_prompt([selected_box_value])
                normalized_selected_box = serialized_selected_boxes[0] if serialized_selected_boxes else None
        if role and text_value:
            normalized_chat_history.append({
                'role': role,
                'text': text_value,
                'selected_box': normalized_selected_box,
            })

    ollama_messages = [{'role': 'user', 'content': text}]

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

        try:
            source_overlay_bytes = _render_current_frame_overlay(source_frame_bytes, source_boxes)
        except ChatbotServiceError as error:
            return jsonify({"error": error.message}), error.status_code

        contextual_images = [{
            'bytes': source_overlay_bytes,
            'mime_type': 'image/jpeg',
            'filename': f"source_view_{source_video_index}_frame_{source_sample_index}_overlay.jpg",
        }]
        boxes_for_current_frame = serialize_boxes_for_prompt(source_boxes)
        target_box = None
        selected_boxes = serialize_boxes_for_prompt(select_box_subset(source_boxes, target_box_id))
        if target_box_id not in (None, '', 'none'):
            target_box = selected_boxes[0] if selected_boxes else None
        image_relationship_text = None

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

            target_boxes = _get_annotation_boxes_for(
                current_user['_id'],
                project['_id'],
                target_video_index,
                target_sample_index,
            )
            try:
                target_overlay_bytes = _render_current_frame_overlay(target_frame_bytes, target_boxes)
            except ChatbotServiceError as error:
                return jsonify({"error": error.message}), error.status_code

            has_additional_frame = True
            image_relationship_text = _describe_image_relationship(
                target_scope,
                source_video_index,
                target_video_index,
                project,
            )
            contextual_images.append({
                'bytes': target_overlay_bytes,
                'mime_type': 'image/jpeg',
                'filename': f"target_view_{target_video_index}_frame_{target_sample_index}_overlay.jpg",
            })

        remaining_history = normalized_chat_history
        first_user_message = None
        if normalized_chat_history and normalized_chat_history[0].get('role') == 'user':
            first_user_message = normalized_chat_history[0]
            remaining_history = normalized_chat_history[1:]

        grounded_first_user = build_contextual_chat_prompt(
            project,
            image_relationship_text=image_relationship_text,
            boxes_for_current_frame=boxes_for_current_frame,
        )
        ollama_messages = [{
            'role': 'user',
            'content': grounded_first_user,
            'images': contextual_images,
        }]
        if first_user_message is not None:
            ollama_messages.append({
                'role': 'user',
                'content': build_turn_user_message(
                    first_user_message.get('text') or '',
                    first_user_message.get('selected_box'),
                ),
            })
        for item in remaining_history:
            content = item['text']
            if item.get('role') == 'user':
                content = build_turn_user_message(item['text'], item.get('selected_box'))
            ollama_messages.append({
                'role': item['role'],
                'content': content,
            })
        ollama_messages.append({
            'role': 'user',
            'content': build_turn_user_message(text, target_box),
        })

    log_agent_messages(
        current_user['_id'],
        project_id,
        ollama_messages,
    )

    @stream_with_context
    def generate_events():
        yield json.dumps({
            "type": "status",
            "message": "Waiting for response",
        }) + "\n"

        try:
            reply = chatbot_service.generate_reply(
                messages=ollama_messages,
            )
        except ChatbotServiceError as error:
            yield json.dumps({
                "type": "error",
                "error": error.message,
                "status_code": error.status_code,
            }) + "\n"
            return

        action_payload = extract_action_json(reply)
        executed_action = None
        action_result = None
        final_reply = reply

        if project_id and action_payload:
            yield json.dumps({
                "type": "status",
                "message": "Executing tools",
            }) + "\n"

            executed_action, action_result = _execute_agent_action(
                action_payload,
                project,
                current_user,
                source_video_index,
                source_sample_index,
                target_scope,
                target_video_index,
                target_sample_index,
            )
            followup_messages = [
                *ollama_messages,
                {
                    'role': 'assistant',
                    'content': reply,
                },
                {
                    'role': 'user',
                    'content': _build_tool_result_message(action_payload, action_result),
                },
            ]

            log_agent_messages(
                current_user['_id'],
                project_id,
                followup_messages,
            )

            yield json.dumps({
                "type": "status",
                "message": "Waiting for response",
            }) + "\n"

            try:
                final_reply = chatbot_service.generate_reply(
                    messages=followup_messages,
                )
            except ChatbotServiceError as error:
                yield json.dumps({
                    "type": "error",
                    "error": error.message,
                    "status_code": error.status_code,
                }) + "\n"
                return

        yield json.dumps({
            "type": "result",
            "reply": strip_action_json(final_reply),
            "model": chatbot_config.model_id,
            "provider": chatbot_config.provider,
            "baseUrl": chatbot_config.base_url,
            "action": executed_action,
            "actionResult": action_result,
        }) + "\n"

    return Response(
        generate_events(),
        mimetype='application/x-ndjson',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )

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
            'boxes': _normalize_boxes_shape_for_export(doc.get('boxes') or []),
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
    return jsonify(_normalize_boxes_shape_for_app(boxes))


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
    normalized_boxes, validation_error = _normalize_and_validate_boxes(boxes, project)
    if validation_error:
        return jsonify({"error": validation_error}), 400

    _upsert_frame_annotations(
        current_user['_id'],
        project['_id'],
        video_index,
        sample_index,
        normalized_boxes,
    )

    return jsonify({
        "success": True,
        "message": (
            f"Saved {len(normalized_boxes)} box(es) for video_index={int(video_index)} "
            f"sample_index={int(sample_index)}"
        ),
        "video_index": int(video_index),
        "sample_index": int(sample_index),
        "boxes_saved": len(normalized_boxes),
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=56250, debug=True)
