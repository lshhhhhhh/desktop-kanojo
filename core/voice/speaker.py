from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from loguru import logger

from .playback import SentencePlayer

if TYPE_CHECKING:
    from PySide6.QtMultimedia import QAudioDevice

    from .base import TTSBackend


class Speaker:
    """Owns a TTSBackend + a per-sentence playback queue. Decouples the
    text-stream side (which enqueues sentences as they're parsed) from the
    audio side (which synthesizes and plays sequentially, one at a time)."""

    def __init__(
        self,
        backend: TTSBackend,
        on_mouth: Callable[[float], None] | None = None,
        *,
        envelope_gain: float = 3.5,
        audio_device: QAudioDevice | None = None,
    ) -> None:
        self.backend = backend
        self.on_mouth = on_mouth
        self._envelope_gain = envelope_gain
        self._audio_device: QAudioDevice | None = audio_device
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._enabled = True

    def set_audio_device(self, device: QAudioDevice | None) -> None:
        """Switch output device. Takes effect on the *next* sentence — the
        currently-playing sentence's sink isn't replaced mid-stream."""
        self._audio_device = device

    def set_backend(self, backend: TTSBackend) -> None:
        """Hot-swap the TTS backend. The currently-playing sentence (if any)
        finishes via the old backend; the next sentence pulled from the queue
        uses the new one. The _run loop reads self.backend at the start of
        each sentence, so no task restart is needed."""
        self.backend = backend
        logger.info("speaker: backend swapped to {}", type(backend).__name__)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._queue.put_nowait(None)

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)

    def is_enabled(self) -> bool:
        return self._enabled

    def enqueue(self, sentence: str) -> None:
        if not self._enabled:
            return
        sentence = (sentence or "").strip()
        if not sentence:
            return
        self._queue.put_nowait(sentence)

    async def _run(self) -> None:
        logger.info("speaker: started")
        while True:
            sentence = await self._queue.get()
            if sentence is None:
                break
            if not self._enabled:
                continue
            player = SentencePlayer(
                on_envelope=self.on_mouth,
                envelope_gain=self._envelope_gain,
                audio_device=self._audio_device,
            )
            try:
                async for chunk in self.backend.speak(sentence):
                    await player.feed(chunk.pcm, chunk.sample_rate, chunk.channels)
            except Exception as e:
                logger.warning("speaker: TTS or playback failed: {}", e)
            finally:
                await player.close()
        logger.info("speaker: stopped")
