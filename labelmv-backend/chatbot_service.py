import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests


DEFAULT_MODEL_ID = "qwen3-vl:8b-instruct"


def _read_int_env(name, default_value):
    value = os.environ.get(name)
    if value is None:
        return default_value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default_value


def _read_float_env(name, default_value):
    value = os.environ.get(name)
    if value is None:
        return default_value
    try:
        return float(value)
    except (TypeError, ValueError):
        return default_value


@dataclass
class ChatbotConfig:
    provider: str
    base_url: str
    request_path: str
    api_key: str
    site_url: str
    site_title: str
    model_id: str
    timeout_seconds: int
    max_tokens: int
    max_prompt_chars: int
    max_image_bytes: int
    ollama_think: str
    seed: int | None
    temperature: float


def load_chatbot_config():
    return ChatbotConfig(
        provider=os.environ.get("CHATBOT_PROVIDER", "ollama").strip().lower() or "ollama",
        base_url=os.environ.get("CHATBOT_BASE_URL", "http://host.docker.internal:11434").strip(),
        request_path=os.environ.get("CHATBOT_REQUEST_PATH", "/api/chat").strip() or "/api/chat",
        api_key=os.environ.get("CHATBOT_API_KEY", "").strip(),
        site_url=os.environ.get("CHATBOT_SITE_URL", "").strip(),
        site_title=os.environ.get("CHATBOT_SITE_TITLE", "").strip(),
        model_id=os.environ.get("CHATBOT_MODEL", DEFAULT_MODEL_ID).strip() or DEFAULT_MODEL_ID,
        timeout_seconds=max(10, _read_int_env("CHATBOT_TIMEOUT_SECONDS", 180)),
        max_tokens=max(32, _read_int_env("CHATBOT_MAX_TOKENS", 256)),
        max_prompt_chars=max(1, _read_int_env("CHATBOT_MAX_PROMPT_CHARS", 12000)),
        max_image_bytes=max(1024, _read_int_env("CHATBOT_MAX_IMAGE_BYTES", 5 * 1024 * 1024)),
        ollama_think=(os.environ.get("CHATBOT_OLLAMA_THINK", "false").strip()),
        seed=(
            _read_int_env("CHATBOT_SEED", 0)
            if os.environ.get("CHATBOT_SEED") not in (None, "")
            else None
        ),
        temperature=_read_float_env("CHATBOT_TEMPERATURE", 0.2),
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
        request_path = self.config.request_path
        if "{model}" in request_path:
            request_path = request_path.format(model=quote(self.config.model_id, safe=""))
        return f"{self.config.base_url.rstrip('/')}/{request_path.lstrip('/')}"

    def _request_headers(self):
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            if self.config.provider == "google_genai":
                headers["x-goog-api-key"] = self.config.api_key
            else:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
        if self.config.provider == "openrouter":
            if self.config.site_url:
                headers["HTTP-Referer"] = self.config.site_url
            if self.config.site_title:
                headers["X-OpenRouter-Title"] = self.config.site_title
        return headers

    def _normalized_ollama_think(self):
        value = (self.config.ollama_think or "").strip().lower()
        if not value:
            return False
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        return self.config.ollama_think.strip()

    def _build_request(self, messages):
        if self.config.provider == "openai":
            input_items = []
            for message in messages:
                text_type = "output_text" if message["role"] == "assistant" else "input_text"
                content = [{"type": text_type, "text": message["content"]}]
                for image in message.get("images") or []:
                    image_b64 = base64.b64encode(image["bytes"]).decode("utf-8")
                    content.append({
                        "type": "input_image",
                        "image_url": f"data:{image['mime_type']};base64,{image_b64}",
                    })
                input_items.append({
                    "role": message["role"],
                    "content": content,
                })
            return {
                "model": self.config.model_id,
                "input": input_items,
                "max_output_tokens": self.config.max_tokens,
            }

        if self.config.provider == "openrouter":
            openrouter_messages = []
            for message in messages:
                content = [{"type": "text", "text": message["content"]}]
                for image in message.get("images") or []:
                    image_b64 = base64.b64encode(image["bytes"]).decode("utf-8")
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image['mime_type']};base64,{image_b64}",
                        },
                    })
                openrouter_messages.append({
                    "role": message["role"],
                    "content": content,
                })
            payload = {
                "model": self.config.model_id,
                "messages": openrouter_messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
            }
            if self.config.seed is not None:
                payload["seed"] = self.config.seed
            return payload

        if self.config.provider == "google_genai":
            contents = []
            for message in messages:
                parts = [{"text": message["content"]}]
                for image in message.get("images") or []:
                    parts.append({
                        "inline_data": {
                            "mime_type": image["mime_type"],
                            "data": base64.b64encode(image["bytes"]).decode("utf-8"),
                        }
                    })
                contents.append({
                    "role": "model" if message["role"] == "assistant" else "user",
                    "parts": parts,
                })
            generation_config = {
                "temperature": self.config.temperature,
                "maxOutputTokens": self.config.max_tokens,
            }
            if self.config.seed is not None:
                generation_config["seed"] = self.config.seed
            return {
                "contents": contents,
                "generationConfig": generation_config,
            }

        ollama_messages = []
        for message in messages:
            item = {
                "role": message["role"],
                "content": message["content"],
            }
            if message.get("images"):
                item["images"] = [
                    base64.b64encode(image["bytes"]).decode("utf-8")
                    for image in message.get("images") or []
                ]
            ollama_messages.append(item)

        ollama_options = {
            "num_predict": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if self.config.seed is not None:
            ollama_options["seed"] = self.config.seed
        payload = {
            "model": self.config.model_id,
            "messages": ollama_messages,
            "stream": False,
            "think": self._normalized_ollama_think(),
            "options": ollama_options,
        }
        return payload

    def _extract_reply(self, data):
        if self.config.provider == "openai":
            output = data.get("output") or []
            texts = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                for content in item.get("content") or []:
                    if isinstance(content, dict) and content.get("type") == "output_text" and content.get("text"):
                        texts.append(content["text"])
            return "\n".join(texts).strip()

        if self.config.provider == "openrouter":
            choices = data.get("choices") or []
            if not choices:
                return ""
            message = (choices[0].get("message") or {})
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                        texts.append(item["text"])
                return "\n".join(texts).strip()
            return ""

        if self.config.provider == "google_genai":
            candidates = data.get("candidates") or []
            if not candidates:
                return ""
            content = (candidates[0].get("content") or {})
            parts = content.get("parts") or []
            texts = [part.get("text", "") for part in parts if isinstance(part, dict) and part.get("text")]
            return "\n".join(texts).strip()

        message = data.get("message") or {}
        content = (message.get("content") or "").strip()
        if content:
            return content
        return (message.get("thinking") or "").strip()

    def _normalize_messages(self, messages):
        normalized = []
        for item in messages or []:
            if not isinstance(item, dict):
                continue
            role = (item.get("role") or "").strip()
            content = self.validate_text(item.get("content") or "")
            if not role or not content:
                continue
            message = {
                "role": role,
                "content": content,
            }
            images = self.validate_images(item.get("images"))
            if images:
                message["images"] = images
            normalized.append(message)
        return normalized

    def _dump_latest_messages(self, messages):
        enabled = os.environ.get("AGENT_INPUT_IMAGE_DUMP", "").strip().lower() in {"1", "true", "yes", "on"}
        if not enabled:
            return

        dump_dir = Path(os.environ.get("AGENT_INPUT_IMAGE_DUMP_DIR", "/tmp")).resolve()
        dump_dir.mkdir(parents=True, exist_ok=True)

        sanitized_messages = []
        latest_images = []
        for message in messages:
            entry = {
                "role": message.get("role"),
                "content": message.get("content"),
                "images": [],
            }
            for image in message.get("images") or []:
                filename = image.get("filename") or "image.jpg"
                entry["images"].append({
                    "filename": filename,
                    "mime_type": image.get("mime_type"),
                    "bytes": len(image.get("bytes") or b""),
                })
                latest_images.append((filename, image.get("bytes") or b""))
            sanitized_messages.append(entry)

        (dump_dir / "agent_latest_messages.json").write_text(
            json.dumps(sanitized_messages, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        for index in range(2):
            image_path = dump_dir / f"agent_latest_image_{index + 1}.jpg"
            if index < len(latest_images):
                _filename, image_bytes = latest_images[index]
                image_path.write_bytes(image_bytes)
            elif image_path.exists():
                image_path.unlink()

    def generate_reply(self, messages):
        normalized_messages = self._normalize_messages(messages)
        if not normalized_messages:
            raise ChatbotServiceError("at least one message is required", status_code=400)

        self._dump_latest_messages(normalized_messages)

        payload = self._build_request(normalized_messages)

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
            try:
                print(
                    "CHATBOT_EMPTY_RESPONSE "
                    + json.dumps(
                        {
                            "provider": self.config.provider,
                            "model": self.config.model_id,
                            "url": self._request_url(),
                            "response_json": data,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except Exception:
                pass
            raise ChatbotServiceError("chatbot server returned an empty response", status_code=502)
        return reply
