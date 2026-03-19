import os

import cv2
import numpy as np

try:
    from ultralytics import YOLOWorld
except Exception:  # pragma: no cover - handled at runtime
    YOLOWorld = None


_DEVICE = "cuda:0"


def _load_model():
    if YOLOWorld is None:
        raise RuntimeError("ultralytics is not installed")
    model_path = os.environ.get("YOLO_MODEL_PATH", "yolov8s-worldv2.pt").strip() or "yolov8s-worldv2.pt"
    return YOLOWorld(model_path)


def _clamp_1000(value):
    return max(0, min(1000, int(round(float(value)))))


def detect_objects(image_bytes, class_name="", max_detections=None):
    if not image_bytes:
        return {"error": "image file is empty"}, 400

    image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return {"error": "failed to decode image"}, 400

    try:
        model = _load_model()
        if class_name:
            model.set_classes([class_name])
        results = model.predict(source=image, verbose=False, device=_DEVICE)
    except Exception as error:
        return {"error": f"yolo-world inference failed: {error}"}, 500

    detections = []
    image_h, image_w = image.shape[:2]
    for result in results:
        names = result.names or {}
        for box in result.boxes:
            cls_index = int(box.cls[0].item())
            detected_class = str(names.get(cls_index, cls_index))
            if class_name and detected_class != class_name:
                continue

            x1, y1, x2, y2 = box.xyxy[0].tolist()
            detections.append({
                "className": detected_class,
                "bbox_1000": [
                    _clamp_1000((x1 / image_w) * 1000.0),
                    _clamp_1000((y1 / image_h) * 1000.0),
                    _clamp_1000((x2 / image_w) * 1000.0),
                    _clamp_1000((y2 / image_h) * 1000.0),
                ],
                "score": round(float(box.conf[0].item()), 4),
            })

    detections.sort(key=lambda item: item["score"], reverse=True)
    if max_detections is not None and max_detections > 0:
        detections = detections[:max_detections]

    return {
        "success": True,
        "detections": detections,
    }, 200
