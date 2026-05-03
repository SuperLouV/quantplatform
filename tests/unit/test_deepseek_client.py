from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from quant_platform.clients.deepseek import DeepSeekClient, DeepSeekClientError, extract_chat_text


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")


class DeepSeekClientTest(unittest.TestCase):
    def test_requires_api_key(self) -> None:
        client = DeepSeekClient(api_key="")
        with self.assertRaises(DeepSeekClientError):
            client.chat([{"role": "user", "content": "hello"}])

    @patch("quant_platform.clients.deepseek.urlopen")
    def test_chat_uses_openai_compatible_endpoint(self, urlopen) -> None:
        urlopen.return_value = _FakeResponse()
        client = DeepSeekClient(api_key="test-key", base_url="https://api.deepseek.com", model="deepseek-v4-flash")

        response = client.chat([{"role": "user", "content": "hello"}], max_tokens=100)

        self.assertEqual(extract_chat_text(response), "ok")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer test-key")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "deepseek-v4-flash")
        self.assertFalse(body["stream"])


if __name__ == "__main__":
    unittest.main()
