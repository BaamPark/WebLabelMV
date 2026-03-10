import base64
import binascii
import io
import os
import tempfile
import threading

from flask import Flask, jsonify, request
from PIL import Image
import torch
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration


def _read_int_env(name, default_value):
    value = os.environ.get(name)
    if value is None:
        return default_value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default_value


MODEL_ID = os.environ.get("MODEL_ID", "Qwen/Qwen3-VL-2B-Instruct").strip() or "Qwen/Qwen3-VL-2B-Instruct"
MODEL_DEVICE = os.environ.get("MODEL_DEVICE", "cpu").strip().lower() or "cpu"
MODEL_DTYPE = os.environ.get("MODEL_DTYPE", "auto").strip().lower() or "auto"
MAX_IMAGE_BYTES = max(1024, _read_int_env("MAX_IMAGE_BYTES", 5 * 1024 * 1024))
DEFAULT_MAX_NEW_TOKENS = max(32, _read_int_env("DEFAULT_MAX_NEW_TOKENS", 256))
MODEL_SERVER_HOST = os.environ.get("MODEL_SERVER_HOST", "0.0.0.0").strip() or "0.0.0.0"
MODEL_SERVER_PORT = _read_int_env("MODEL_SERVER_PORT", 8000)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES + 1024 * 1024

_model = None
_processor = None
_load_lock = threading.Lock()


def _torch_dtype():
    if MODEL_DTYPE == "auto":
        return "auto"
    mapping = {
        "float32": torch.float32,
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
    }
    return mapping.get(MODEL_DTYPE, "auto")


def _load_model():
    global _model, _processor
    if _model is not None and _processor is not None:
        return _model, _processor

    with _load_lock:
        if _model is not None and _processor is not None:
            return _model, _processor

        load_kwargs = {"torch_dtype": _torch_dtype()}
        if MODEL_DEVICE == "auto":
            load_kwargs["device_map"] = "auto"

        model = Qwen3VLForConditionalGeneration.from_pretrained(
            MODEL_ID,
            **load_kwargs,
        )
        if MODEL_DEVICE != "auto":
            model = model.to(MODEL_DEVICE)
        processor = AutoProcessor.from_pretrained(MODEL_ID)

        _model = model
        _processor = processor
        return _model, _processor


def _decode_image(image_base64):
    if not image_base64:
        return None

    payload = image_base64
    if "," in payload and payload.split(",", 1)[0].startswith("data:"):
        payload = payload.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(payload)
    except (ValueError, binascii.Error) as error:
        raise ValueError(f"invalid image_base64 payload: {error}")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError(f"image must be at most {MAX_IMAGE_BYTES} bytes")
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.verify()
    except Exception as error:
        raise ValueError(f"invalid image data: {error}")
    return image_bytes


def _materialize_image(image_bytes, image_name):
    if not image_bytes:
        return None

    suffix = os.path.splitext(image_name or "upload.png")[1] or ".png"
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        temp_file.write(image_bytes)
        temp_file.flush()
        return temp_file.name
    finally:
        temp_file.close()


def _generate_reply(text, image_path, max_new_tokens, temperature):
    model, processor = _load_model()

    content = []
    if image_path:
        content.append({"type": "image", "image": image_path})
    if text:
        content.append({"type": "text", "text": text})
    if not content:
        raise ValueError("text or image is required")

    messages = [{"role": "user", "content": content}]
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )
    inputs = inputs.to(model.device)

    generation_kwargs = {
        "max_new_tokens": max_new_tokens,
    }
    if temperature and temperature > 0:
        generation_kwargs["do_sample"] = True
        generation_kwargs["temperature"] = temperature

    with torch.inference_mode():
        generated_ids = model.generate(**inputs, **generation_kwargs)

    generated_ids_trimmed = [
        out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = processor.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )
    return (output_text[0] if output_text else "").strip()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "model": MODEL_ID,
        "device": MODEL_DEVICE,
        "loaded": _model is not None,
    })


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    image_base64 = data.get("image_base64")
    image_name = data.get("image_name") or "upload.png"
    max_new_tokens = max(32, int(data.get("max_new_tokens") or DEFAULT_MAX_NEW_TOKENS))
    temperature = float(data.get("temperature") or 0.2)

    image_path = None
    try:
        image_bytes = _decode_image(image_base64)
        image_path = _materialize_image(image_bytes, image_name)
        reply = _generate_reply(text, image_path, max_new_tokens, temperature)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"generation failed: {error}"}), 500
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)

    if not reply:
        return jsonify({"error": "model returned an empty response"}), 502

    return jsonify({
        "reply": reply,
        "model": MODEL_ID,
        "device": MODEL_DEVICE,
    })


if __name__ == "__main__":
    app.run(host=MODEL_SERVER_HOST, port=MODEL_SERVER_PORT)
