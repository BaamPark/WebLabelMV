import base64
import os
from dataclasses import dataclass

import requests


DEFAULT_MODEL_ID = "Qwen/Qwen3-VL-2B-Instruct"


def _read_int_env(name, default_value):
    value = os.environ.get(name)
    if value is None:
        return default_value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default_value


@dataclass
class ChatbotConfig:
    provider: str
    base_url: str
    request_path: str
    api_key: str
    model_id: str
    timeout_seconds: int
    max_tokens: int
    max_prompt_chars: int
    max_image_bytes: int


def load_chatbot_config():
    return ChatbotConfig(
        provider=os.environ.get("CHATBOT_PROVIDER", "ollama").strip().lower() or "ollama",
        base_url=os.environ.get("CHATBOT_BASE_URL", "http://host.docker.internal:11434").strip(),
        request_path=os.environ.get("CHATBOT_REQUEST_PATH", "/api/generate").strip() or "/api/generate",
        api_key=os.environ.get("CHATBOT_API_KEY", "").strip(),
        model_id=os.environ.get("CHATBOT_MODEL", DEFAULT_MODEL_ID).strip() or DEFAULT_MODEL_ID,
        timeout_seconds=max(10, _read_int_env("CHATBOT_TIMEOUT_SECONDS", 180)),
        max_tokens=max(32, _read_int_env("CHATBOT_MAX_TOKENS", 256)),
        max_prompt_chars=max(1, _read_int_env("CHATBOT_MAX_PROMPT_CHARS", 12000)),
        max_image_bytes=max(1024, _read_int_env("CHATBOT_MAX_IMAGE_BYTES", 5 * 1024 * 1024)),
    )


class ChatbotServiceError(Exception):
    def __init__(self, message, status_code=500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ChatbotProxyService:
    def __init__(self, config):
        self.config = config

    def validate_text(self, text):
        normalized = (text or "").strip()
        if len(normalized) > self.config.max_prompt_chars:
            raise ChatbotServiceError(
                f"text must be at most {self.config.max_prompt_chars} characters",
                status_code=400,
            )
        return normalized

    def validate_image(self, image_bytes, mime_type, filename):
        if not image_bytes:
            return None, None, None
        if len(image_bytes) > self.config.max_image_bytes:
            raise ChatbotServiceError(
                f"image must be at most {self.config.max_image_bytes} bytes",
                status_code=400,
            )
        normalized_mime_type = mime_type or "application/octet-stream"
        if not normalized_mime_type.startswith("image/"):
            raise ChatbotServiceError("uploaded file must be an image", status_code=400)
        return image_bytes, normalized_mime_type, filename or "upload"

    def validate_images(self, images):
        normalized = []
        for image in images or []:
            if not isinstance(image, dict):
                continue
            image_bytes, mime_type, filename = self.validate_image(
                image.get("bytes"),
                image.get("mime_type"),
                image.get("filename"),
            )
            if image_bytes:
                normalized.append({
                    "bytes": image_bytes,
                    "mime_type": mime_type,
                    "filename": filename,
                })
        return normalized

    def _request_url(self):
        if not self.config.base_url:
            raise ChatbotServiceError("CHATBOT_BASE_URL is not configured", status_code=503)
        return f"{self.config.base_url.rstrip('/')}/{self.config.request_path.lstrip('/')}"

    def _request_headers(self):
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _build_request(self, prompt_text, images):
        payload = {
            "model": self.config.model_id,
            "prompt": prompt_text,
            "stream": False,
            "options": {
                "num_predict": self.config.max_tokens,
                "temperature": 0.2,
            },
        }
        if images:
            payload["images"] = [
                base64.b64encode(item["bytes"]).decode("utf-8")
                for item in images
            ]
        return payload

    def _extract_reply(self, data):
        return (data.get("response") or "").strip()

    def generate_reply(self, text, image_bytes=None, mime_type=None, filename=None, images=None):
        prompt_text = self.validate_text(text)
        normalized_images = self.validate_images(images)
        image_bytes, mime_type, filename = self.validate_image(image_bytes, mime_type, filename)
        if image_bytes:
            normalized_images.append({
                "bytes": image_bytes,
                "mime_type": mime_type,
                "filename": filename,
            })

        if not prompt_text and not normalized_images:
            raise ChatbotServiceError("text or image is required", status_code=400)

        payload = self._build_request(prompt_text, normalized_images)

        try:
            response = requests.post(
                self._request_url(),
                json=payload,
                headers=self._request_headers(),
                timeout=self.config.timeout_seconds,
            )
        except requests.Timeout:
            raise ChatbotServiceError("chatbot server timed out", status_code=504)
        except requests.RequestException as error:
            raise ChatbotServiceError(f"chatbot server request failed: {error}", status_code=502)

        try:
            data = response.json()
        except ValueError:
            data = {}

        if not response.ok:
            message = data.get("error") or f"chatbot server returned {response.status_code}"
            raise ChatbotServiceError(message, status_code=502)

        reply = self._extract_reply(data)
        if not reply:
            raise ChatbotServiceError("chatbot server returned an empty response", status_code=502)
        return reply
