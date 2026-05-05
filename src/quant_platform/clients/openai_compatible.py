"""Small OpenAI-compatible chat client for local or hosted models."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from quant_platform.config import AIConfig


class OpenAICompatibleClientError(RuntimeError):
    """Raised when an OpenAI-compatible API request fails."""


class OpenAICompatibleClient:
    """Minimal `/chat/completions` client.

    Local OpenAI-compatible servers often do not require an API key. Hosted
    providers usually do, so callers decide whether missing credentials should
    skip model calls before constructing this client.
    """

    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.provider_name = provider_name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_ai_config(cls, config: AIConfig) -> "OpenAICompatibleClient":
        return cls(
            provider_name=config.provider,
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
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
        if not self.base_url:
            raise OpenAICompatibleClientError("AI base_url is required.")
        if not self.model:
            raise OpenAICompatibleClientError("AI model is required.")
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
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OpenAICompatibleClientError(f"AI API returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise OpenAICompatibleClientError(f"AI API request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise OpenAICompatibleClientError("AI API returned non-JSON response.") from exc
        if not isinstance(decoded, dict):
            raise OpenAICompatibleClientError("AI API response must be a JSON object.")
        return decoded


def extract_chat_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise OpenAICompatibleClientError("AI response missing choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise OpenAICompatibleClientError("AI response choice must be an object.")
    message = first.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise OpenAICompatibleClientError("AI response missing message.content.")
    return message["content"]
