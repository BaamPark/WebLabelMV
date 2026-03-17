import json
import os


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


def build_contextual_chat_prompt(user_text, project, has_additional_frame=False,
                                 boxes_for_current_frame=None, target_box=None, chat_history=None):
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
    if chat_history:
        payload['chat_history'] = chat_history

    image_order = "Image order:\n- Image 1: current frame\n"
    if has_additional_frame:
        image_order += "- Image 2 (if present): target frame\n"

    instructions = (
        "You are assisting a multi-view annotation workflow. "
        f"{image_order}"
        "Bounding boxes are expressed as [x1, y1, x2, y2] normalized to the range [0, 1000]. "
        "Use only the provided context. If a frame or box context is omitted, do not invent it."
    )
    return (
        f"{instructions}\n\n"
        f"Context JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"User Query:\n{user_text}"
    )


def log_agent_input(user_id, project_id, prompt_text, images):
    enabled = os.environ.get('AGENT_INPUT_LOGGING', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    if not enabled:
        return

    image_meta = []
    for index, image in enumerate(images or [], start=1):
        image_meta.append({
            'index': index,
            'filename': image.get('filename'),
            'mime_type': image.get('mime_type'),
            'bytes': len(image.get('bytes') or b''),
        })

    print(
        "AGENT_INPUT " + json.dumps({
            'user_id': str(user_id),
            'project_id': str(project_id) if project_id is not None else None,
            'images': image_meta,
            'prompt': prompt_text,
        }, ensure_ascii=False),
        flush=True,
    )
