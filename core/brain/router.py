from __future__ import annotations

from typing import Any

from loguru import logger

from .base import LLMBackend
from .openai_compat import OpenAICompatBackend


class Router:
    """Selects an LLMBackend by intent name, falling back to default."""

    def __init__(
        self,
        backends: dict[str, LLMBackend],
        routing: dict[str, str],
        default: str,
    ) -> None:
        if default not in backends:
            raise ValueError(f"default backend '{default}' not in backends")
        self.backends = backends
        self.routing = routing
        self.default = default

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> Router:
        brain = cfg["brain"]
        backends: dict[str, LLMBackend] = {}

        for name, b in brain["backends"].items():
            provider = b["provider"]
            if provider == "openai_compat":
                backends[name] = OpenAICompatBackend(
                    name=name,
                    base_url=b["base_url"],
                    model=b["model"],
                    api_key=b.get("api_key"),
                    api_key_env=b.get("api_key_env"),
                    vision=b.get("vision", True),
                    extra_body=b.get("extra_body"),
                    supports_temperature=b.get("supports_temperature", True),
                )
            else:
                raise ValueError(f"Unknown provider: {provider}")

        routing = brain.get("routing", {}) or {}
        default = brain.get("default") or routing.get("default")
        if not default:
            raise ValueError("brain.default or brain.routing.default must be set")

        return cls(backends=backends, routing=routing, default=default)

    def select(self, intent: str = "default") -> LLMBackend:
        name = self.routing.get(intent, self.default)
        backend = self.backends.get(name)
        if backend is None:
            logger.warning("Unknown backend '{}' for intent '{}', using default", name, intent)
            backend = self.backends[self.default]
        return backend
