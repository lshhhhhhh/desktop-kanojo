from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass
class ContentPart:
    type: Literal["text", "image"]
    text: str | None = None
    image_b64: str | None = None
    image_mime: str = "image/png"


@dataclass
class Message:
    role: Role
    content: list[ContentPart] = field(default_factory=list)

    @classmethod
    def text(cls, role: Role, text: str) -> Message:
        return cls(role=role, content=[ContentPart(type="text", text=text)])


@dataclass
class ChatRequest:
    messages: list[Message]
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = True


@dataclass
class ChatChunk:
    delta: str
    finish_reason: str | None = None


class LLMBackend(ABC):
    name: str

    @abstractmethod
    async def chat(self, req: ChatRequest) -> AsyncIterator[ChatChunk]:
        """Stream chat completions. Yields ChatChunk objects."""

    @abstractmethod
    def supports_vision(self) -> bool: ...
