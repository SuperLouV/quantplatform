"""DeepSeek OpenAI-compatible chat client."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from quant_platform.config import AIConfig


class DeepSeekClientError(RuntimeError):
    """Raised when DeepSeek API configuration or responses are invalid."""


class DeepSeekClient:
    provider_name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_ai_config(cls, config: AIConfig) -> "DeepSeekClient":
        return cls(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
            model=config.deepseek_model,
            timeout_seconds=config.request_timeout_seconds,
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise DeepSeekClientError("DEEPSEEK_API_KEY is required for model-backed analysis.")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if response_format:
            payload["response_format"] = response_format
        return self._post_json("/chat/completions", payload)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DeepSeekClientError(f"DeepSeek API returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise DeepSeekClientError(f"DeepSeek API request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise DeepSeekClientError("DeepSeek API returned non-JSON response.") from exc
        if not isinstance(decoded, dict):
            raise DeepSeekClientError("DeepSeek API response must be a JSON object.")
        return decoded


def extract_chat_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise DeepSeekClientError("DeepSeek response missing choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise DeepSeekClientError("DeepSeek response choice must be an object.")
    message = first.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise DeepSeekClientError("DeepSeek response missing message.content.")
    return message["content"]
