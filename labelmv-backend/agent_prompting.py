import json
import os
import re


def _clamp_grounding(value):
    return max(0, min(1000, int(round(float(value)))))


def box_to_grounding(box):
    left = float(box.get('left') or 0.0)
    top = float(box.get('top') or 0.0)
    width = float(box.get('width') or 0.0)
    height = float(box.get('height') or 0.0)
    return {
        'x1': _clamp_grounding(left * 1000.0),
        'y1': _clamp_grounding(top * 1000.0),
        'x2': _clamp_grounding((left + width) * 1000.0),
        'y2': _clamp_grounding((top + height) * 1000.0),
    }


def select_box_subset(boxes, target_box_id):
    if target_box_id == 'all':
        return boxes
    if not target_box_id or target_box_id == 'none':
        return []
    target_box_id = str(target_box_id)
    return [box for box in boxes if str(box.get('id')) == target_box_id]


def serialize_boxes_for_prompt(boxes):
    items = []
    for box in boxes or []:
        grounding = box_to_grounding(box)
        items.append({
            'boxId': box.get('id'),
            'className': box.get('className') or '',
            'id': box.get('objectId'),
            'attributes': box.get('attributes') or {},
            'bbox_1000': [grounding['x1'], grounding['y1'], grounding['x2'], grounding['y2']],
        })
    return items


def build_turn_user_message(user_text, selected_box=None):
    normalized_text = (user_text or '').strip()
    if selected_box is None:
        return normalized_text
    payload = {
        'selected_box_from_current_frame': selected_box,
    }
    return (
        f"Current Turn Context JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"User Query:\n{normalized_text}"
    )


def build_contextual_chat_prompt(project, image_relationship_text=None,
                                 boxes_for_current_frame=None):
    payload = {
        'task': 'Answer the user question using the provided annotation context. Do not propose or execute actions unless the user explicitly asks for analysis of possible edits.',
        'project': {
            'classes': project.get('classes') or [],
            'attributeDescriptions': project.get('attribute_descriptions') or {},
        },
        'frame_context': {
            'current_frame': 'available via tools',
            'target_frame': image_relationship_text or None,
        },
    }
    if boxes_for_current_frame is not None:
        payload['boxes_for_current_frame'] = boxes_for_current_frame

    action_instructions = (
        "You do not directly perceive image pixels in this workflow. When you need visual evidence, call the "
        "detect_object tool first and reason from its returned detections. "
        "If the user asks you to create a new annotation box or adjust an existing box, append exactly one final "
        "line beginning with ACTION_JSON: followed by compact JSON on the same line. "
        "Do not output bare JSON without the ACTION_JSON: prefix. "
        "One-shot example: ACTION_JSON: {\"action\":\"update_box_object_id\",\"target_frame\":\"current\",\"box_id\":\"x82lq2\",\"objectId\":1}. "
        "For the supported detection tool, use this schema: "
        "{\"action\":\"detect_object\",\"target_frame\":\"current|target\",\"className\":\"<project class or empty>\","
        "\"max_detections\":<positive integer optional>}. "
        "For the supported create action, use either this single-box schema: "
        "{\"action\":\"create_box\",\"target_frame\":\"current|target\",\"className\":\"<project class>\","
        "\"bbox_1000\":[x1,y1,x2,y2]} "
        "or this multi-box schema: "
        "{\"action\":\"create_box\",\"target_frame\":\"current|target\",\"boxes\":[{\"className\":\"<project class>\","
        "\"bbox_1000\":[x1,y1,x2,y2]}]}. "
        "For the supported geometry update action, use this schema: "
        "{\"action\":\"update_box_geometry\",\"target_frame\":\"current|target\",\"box_id\":\"<existing box id>\","
        "\"bbox_1000\":[x1,y1,x2,y2]}. "
        "For the supported class update action, use this schema: "
        "{\"action\":\"update_box_class\",\"target_frame\":\"current|target\",\"box_id\":\"<existing box id>\","
        "\"className\":\"<project class>\"}. "
        "For the supported attribute update action, use this schema: "
        "{\"action\":\"update_box_attributes\",\"target_frame\":\"current|target\",\"box_id\":\"<existing box id>\","
        "\"attributes\":{\"<attribute name>\":\"<attribute code or empty string>\"}}. "
        "For the supported object identity update action, use this schema: "
        "{\"action\":\"update_box_object_id\",\"target_frame\":\"current|target\",\"box_id\":\"<existing box id>\","
        "\"objectId\":<non-negative integer>}. "
        "Use bbox_1000 integers in [0,1000]. Use target_frame=\"target\" only when a target frame is available. "
        "In context JSON, user-facing tracking id is shown as id, while boxId is the internal box reference key. "
        "When the user says update the id, they mean the tracking/object id, not boxId. "
        "Do not include objectId or attributes for create_box; the backend will set defaults."
    )

    instructions = (
        "You are assisting a multi-view annotation workflow. "
        "Bounding boxes are expressed as [x1, y1, x2, y2] normalized to the range [0, 1000]. "
        "Use only the provided context. If a frame or box context is omitted, do not invent it. "
        "You may use more than one tool step: for example, call detect_object first, read the tool result, "
        "and then call an annotation tool. After all needed tools are done, produce a normal final response. "
        f"{action_instructions}"
    )
    return (
        f"{instructions}\n\n"
        f"Context JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def extract_action_json(reply_text):
    if not isinstance(reply_text, str):
        return None
    matches = re.findall(r'^ACTION_JSON:\s*(\{.*\})\s*$', reply_text, flags=re.MULTILINE)
    candidates = list(matches)

    stripped = reply_text.strip()
    if stripped.startswith('{') and stripped.endswith('}'):
        candidates.append(stripped)
    else:
        for line in reply_text.splitlines():
            candidate = line.strip()
            if candidate.startswith('{') and candidate.endswith('}'):
                candidates.append(candidate)

    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get('action'), str) and parsed.get('action').strip():
            return parsed
    return None


def strip_action_json(reply_text):
    if not isinstance(reply_text, str):
        return ''
    stripped = reply_text.strip()
    if stripped.startswith('{') and stripped.endswith('}'):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(parsed, dict) and isinstance(parsed.get('action'), str) and parsed.get('action').strip():
                return ''
    cleaned = re.sub(r'^\s*ACTION_JSON:\s*\{.*\}\s*$', '', reply_text, flags=re.MULTILINE)
    lines = []
    for line in cleaned.splitlines():
        candidate = line.strip()
        if candidate.startswith('{') and candidate.endswith('}'):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                lines.append(line)
                continue
            if isinstance(parsed, dict) and isinstance(parsed.get('action'), str) and parsed.get('action').strip():
                continue
        lines.append(line)
    return '\n'.join(lines).strip()


def log_agent_input(user_id, project_id, prompt_text, images):
    enabled = os.environ.get('AGENT_INPUT_LOGGING', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    if not enabled:
        return


def log_agent_messages(user_id, project_id, messages):
    enabled = os.environ.get('AGENT_INPUT_LOGGING', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    if not enabled:
        return

    sanitized = []
    for message in messages or []:
        entry = {
            'role': message.get('role'),
            'content': message.get('content'),
        }
        if message.get('images'):
            entry['images'] = [{
                'filename': image.get('filename'),
                'mime_type': image.get('mime_type'),
                'bytes': len(image.get('bytes') or b''),
            } for image in message.get('images') or []]
        sanitized.append(entry)

    print(
        "AGENT_INPUT " + json.dumps({
            'user_id': str(user_id),
            'project_id': str(project_id) if project_id is not None else None,
            'messages': sanitized,
        }, ensure_ascii=False),
        flush=True,
    )
