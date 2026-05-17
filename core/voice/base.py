from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


@dataclass
class AudioChunk:
    """A chunk of int16 mono PCM, ready to feed sounddevice."""

    pcm: bytes
    sample_rate: int
    channels: int = 1


class TTSBackend(ABC):
    """Synthesize text → stream PCM chunks. Implementations may buffer
    internally (e.g. for codec decode) and yield one large chunk per call."""

    @abstractmethod
    async def speak(self, text: str) -> AsyncIterator[AudioChunk]:
        """Yield AudioChunks for this text. Caller handles playback + lip sync."""

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "TTSBackend":  # noqa: D401
        """Factory: read `voice` block, dispatch to right backend."""
        voice = cfg.get("voice") or {}
        backend_name = voice.get("backend", "edge-tts")
        if backend_name == "edge-tts":
            from .edge_tts_backend import EdgeTTSBackend
            return EdgeTTSBackend.from_config(voice.get("edge_tts") or {})
        if backend_name == "gpt-sovits":
            from .sovits_backend import GPTSoVITSBackend
            return GPTSoVITSBackend.from_config(voice.get("sovits") or {})
        raise ValueError(f"unknown voice.backend: {backend_name!r}")
