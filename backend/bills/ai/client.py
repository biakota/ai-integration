"""Thin seam between our code and whatever model you choose.

Only a fake client ships with the exercise. Add a real one (hosted API,
local model, ...) behind the same interface if your design needs it, or
replace the interface entirely — just explain the choice in NOTES.md.
"""

from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@dataclass
class TextPart:
    text: str


@dataclass
class ImagePart:
    data: bytes
    media_type: str  # "image/png", "image/jpeg", ...


@dataclass
class LLMRequest:
    system: str
    parts: list[TextPart | ImagePart]
    response_schema: dict | None = None


class LLMClient(ABC):
    @abstractmethod
    def complete(self, request: LLMRequest) -> str:
        """Send the request, return the model's raw text answer."""


@dataclass
class FakeLLMClient(LLMClient):
    """Returns canned answers and records every request it receives.

    `requests` is exactly what would have left the server with a real
    provider — useful for tests.
    """

    responses: list[str] = field(default_factory=list)
    requests: list[LLMRequest] = field(default_factory=list)

    def complete(self, request: LLMRequest) -> str:
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else "{}"


class OllamaClient(LLMClient):
    """A model served by Ollama (https://ollama.com), e.g. qwen2.5:7b.

    Usually local, but nothing here relies on that: requests only ever reach
    it through the privacy guard, like any other provider.
    """

    def __init__(self, host: str, model: str, timeout: float = 300):
        self.url = host.rstrip("/") + "/api/chat"
        self.model, self.timeout = model, timeout

    def complete(self, request: LLMRequest) -> str:
        if any(not isinstance(p, TextPart) for p in request.parts):
            raise ValueError("OllamaClient only sends text.")
        body = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": "\n\n".join(p.text for p in request.parts)},
            ],
        }
        print("Sending request to Ollama:")
        if request.response_schema:
            body["format"] = request.response_schema  # constrained JSON output
        http_request = urllib.request.Request(
            self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
            return json.loads(response.read())["message"]["content"]


def _build_client() -> LLMClient:
    if settings.AI_PROVIDER == "fake":
        return FakeLLMClient()
    if settings.AI_PROVIDER == "ground_truth":
        from .ground_truth import GroundTruthClient

        return GroundTruthClient()
    if settings.AI_PROVIDER == "ollama":
        print("Using Ollama model backend:", settings.OLLAMA_MODEL)
        return OllamaClient(settings.OLLAMA_HOST, settings.OLLAMA_MODEL)
    raise ImproperlyConfigured(
        f"No LLM client for AI_PROVIDER={settings.AI_PROVIDER!r}. "
        "Add one in bills/ai/client.py."
    )


def get_llm_client():
    """The configured client, always behind the personal-information guard."""
    from bills.privacy.guard import PrivacyGuardedClient

    return PrivacyGuardedClient(_build_client())
