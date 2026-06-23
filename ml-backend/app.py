import os

from flask import Flask, jsonify, request

from controllers.sam3_controller import detect_objects as detect_objects_with_sam3
from controllers.yolo_controller import detect_objects


app = Flask(__name__)


def _detection_backend():
    return (os.environ.get("DETECTION_BACKEND", "yolo_world").strip().lower() or "yolo_world")


@app.route("/detect", methods=["POST"])
def detect():
    if "image" not in request.files:
        return jsonify({"error": "image file is required"}), 400

    image_file = request.files["image"]
    image_bytes = image_file.read()
    if not image_bytes:
        return jsonify({"error": "image file is empty"}), 400

    class_name = (request.form.get("class_name") or "").strip()

    backend = _detection_backend()
    detector = {
        "sam3": detect_objects_with_sam3,
        "yolo": detect_objects,
        "yolo_world": detect_objects,
    }.get(backend)
    if detector is None:
        return jsonify({
            "error": (
                f"unsupported DETECTION_BACKEND '{backend}'; "
                "expected 'yolo_world' or 'sam3'"
            )
        }), 500

    payload, status_code = detector(
        image_bytes,
        class_name=class_name,
    )
    if isinstance(payload, dict):
        payload.setdefault("detection_backend", backend)
    return jsonify(payload), status_code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)
