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
            'id': box.get('id'),
            'className': box.get('className') or '',
            'objectId': box.get('objectId'),
            'attributes': box.get('attributes') or {},
            'bbox_1000': [grounding['x1'], grounding['y1'], grounding['x2'], grounding['y2']],
        })
    return items


def build_contextual_chat_prompt(user_text, project, image_relationship_text=None,
                                 boxes_for_current_frame=None, target_box=None):
    payload = {
        'task': 'Answer the user question using the provided annotation context. Do not propose or execute actions unless the user explicitly asks for analysis of possible edits.',
        'project': {
            'classes': project.get('classes') or [],
            'attributeDescriptions': project.get('attribute_descriptions') or {},
        },
    }
    if boxes_for_current_frame is not None:
        payload['boxes_for_current_frame'] = boxes_for_current_frame
    if target_box is not None:
        payload['selected_box_from_current_frame'] = target_box

    image_order = "Image order:\n- Image 1: current frame\n"
    if image_relationship_text:
        image_order += f"- Image 2: {image_relationship_text}\n"
        image_order += "- Target frame: Image 2\n"
    else:
        image_order += "- Target frame: Image 1\n"

    action_instructions = (
        "If the user asks you to create a new annotation box, append exactly one final line beginning with "
        "ACTION_JSON: followed by compact JSON on the same line. "
        "For the supported create action, use this schema: "
        "{\"action\":\"create_box\",\"target_frame\":\"current|target\",\"className\":\"<project class>\","
        "\"bbox_1000\":[x1,y1,x2,y2]}. "
        "Use bbox_1000 integers in [0,1000]. Use target_frame=\"target\" only when a target frame is available. "
        "Do not include objectId or attributes for create_box; the backend will set defaults."
    )

    instructions = (
        "You are assisting a multi-view annotation workflow. "
        f"{image_order}"
        "Bounding boxes are expressed as [x1, y1, x2, y2] normalized to the range [0, 1000]. "
        "Use only the provided context. If a frame or box context is omitted, do not invent it. "
        f"{action_instructions}"
    )
    return (
        f"{instructions}\n\n"
        f"Context JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"User Query:\n{user_text}"
    )


def extract_action_json(reply_text):
    if not isinstance(reply_text, str):
        return None
    matches = re.findall(r'^ACTION_JSON:\s*(\{.*\})\s*$', reply_text, flags=re.MULTILINE)
    if not matches:
        return None
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError:
        return None


def strip_action_json(reply_text):
    if not isinstance(reply_text, str):
        return ''
    return re.sub(r'^\s*ACTION_JSON:\s*\{.*\}\s*$', '', reply_text, flags=re.MULTILINE).strip()


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
