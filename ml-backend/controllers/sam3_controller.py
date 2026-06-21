import os
import tempfile
import threading

import cv2
import numpy as np

try:
    from ultralytics.models.sam import SAM3SemanticPredictor
except Exception:  # pragma: no cover - handled at runtime
    SAM3SemanticPredictor = None


_MODEL_LOCK = threading.Lock()
_FEATURE_PREDICTOR = None
_INFERENCE_PREDICTOR = None


def _read_float_env(name, default_value):
    try:
        return float(os.environ.get(name, default_value))
    except (TypeError, ValueError):
        return default_value


def _read_bool_env(name, default_value):
    value = os.environ.get(name)
    if value is None:
        return default_value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _clamp_1000(value):
    return max(0, min(1000, int(round(float(value)))))


def _to_numpy(value):
    if value is None:
        return None
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    return np.asarray(value)


def _normalize_boxes(boxes, image_w, image_h, class_name):
    boxes_np = _to_numpy(boxes)
    if boxes_np is None:
        return []
    boxes_np = np.asarray(boxes_np)
    if boxes_np.size == 0:
        return []
    boxes_np = boxes_np.reshape(-1, boxes_np.shape[-1])

    detections = []
    for row in boxes_np:
        if len(row) < 4:
            continue
        x1, y1, x2, y2 = [float(value) for value in row[:4]]
        if x2 <= x1 or y2 <= y1:
            continue

        detection = {
            "className": class_name,
            "bbox_1000": [
                _clamp_1000((x1 / image_w) * 1000.0),
                _clamp_1000((y1 / image_h) * 1000.0),
                _clamp_1000((x2 / image_w) * 1000.0),
                _clamp_1000((y2 / image_h) * 1000.0),
            ],
        }
        if len(row) >= 5:
            detection["score"] = round(float(row[4]), 4)
        else:
            detection["score"] = 1.0
        detections.append(detection)
    return detections


def _bbox_iou(box_a, box_b):
    ax1, ay1, ax2, ay2 = box_a["bbox_1000"]
    bx1, by1, bx2, by2 = box_b["bbox_1000"]
    intersection_w = max(0, min(ax2, bx2) - max(ax1, bx1))
    intersection_h = max(0, min(ay2, by2) - max(ay1, by1))
    intersection = intersection_w * intersection_h
    if intersection == 0:
        return 0.0

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _non_maximum_suppression(detections):
    iou_threshold = _read_float_env("SAM3_NMS_IOU", 0.3)
    ranked = sorted(detections, key=lambda item: item.get("score", 0.0), reverse=True)
    kept = []
    for detection in ranked:
        if all(_bbox_iou(detection, existing) < iou_threshold for existing in kept):
            kept.append(detection)
    return kept


def _load_predictors():
    global _FEATURE_PREDICTOR, _INFERENCE_PREDICTOR
    if SAM3SemanticPredictor is None:
        raise RuntimeError("ultralytics SAM3 support is not installed")
    if _FEATURE_PREDICTOR is not None and _INFERENCE_PREDICTOR is not None:
        return _FEATURE_PREDICTOR, _INFERENCE_PREDICTOR

    default_model_path = "/home/beomseok/WebLabelMV/ml-backend/sam3.pt"
    model_path = os.environ.get("SAM3_MODEL_PATH", default_model_path).strip() or default_model_path
    overrides = {
        "conf": _read_float_env("SAM3_CONFIDENCE", 0.25),
        "task": "segment",
        "mode": "predict",
        "model": model_path,
        "half": _read_bool_env("SAM3_HALF", True),
        "verbose": False,
    }
    _FEATURE_PREDICTOR = SAM3SemanticPredictor(overrides=overrides)
    _INFERENCE_PREDICTOR = SAM3SemanticPredictor(overrides=overrides)
    _INFERENCE_PREDICTOR.setup_model()
    return _FEATURE_PREDICTOR, _INFERENCE_PREDICTOR


def detect_objects(image_bytes, class_name="", max_detections=None):
    if not image_bytes:
        return {"error": "image file is empty"}, 400
    if not class_name:
        return {"error": "class_name is required for SAM3 text-prompt detection"}, 400

    image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return {"error": "failed to decode image"}, 400

    image_h, image_w = image.shape[:2]
    try:
        with _MODEL_LOCK:
            feature_predictor, inference_predictor = _load_predictors()
            with tempfile.NamedTemporaryFile(suffix=".jpg") as temp_image:
                cv2.imwrite(temp_image.name, image)
                feature_predictor.set_image(temp_image.name)
                _masks, boxes = inference_predictor.inference_features(
                    feature_predictor.features,
                    src_shape=image.shape[:2],
                    text=[class_name],
                )
            detections = _non_maximum_suppression(
                _normalize_boxes(boxes, image_w, image_h, class_name)
            )
    except Exception as error:
        return {"error": f"sam3 inference failed: {error}"}, 500

    detections.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    if max_detections is not None and max_detections > 0:
        detections = detections[:max_detections]

    return {
        "success": True,
        "detections": detections,
    }, 200
