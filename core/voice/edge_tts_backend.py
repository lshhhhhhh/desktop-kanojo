from __future__ import annotations

import io
from collections.abc import AsyncIterator

import edge_tts
import miniaudio
from loguru import logger

from .base import AudioChunk, TTSBackend


class EdgeTTSBackend(TTSBackend):
    """Edge TTS streams MP3. We accumulate the full MP3 per call and decode
    to int16 mono PCM via miniaudio (pure C, no ffmpeg). Sentence-grained.
    """

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        volume: str = "+0%",
        target_sample_rate: int = 24000,
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.volume = volume
        self.target_sample_rate = target_sample_rate

    @classmethod
    def from_config(cls, cfg: dict) -> "EdgeTTSBackend":
        return cls(
            voice=cfg.get("voice", "zh-CN-XiaoxiaoNeural"),
            rate=cfg.get("rate", "+0%"),
            pitch=cfg.get("pitch", "+0Hz"),
            volume=cfg.get("volume", "+0%"),
            target_sample_rate=int(cfg.get("target_sample_rate", 24000)),
        )

    async def speak(self, text: str) -> AsyncIterator[AudioChunk]:
        text = text.strip()
        if not text:
            return

        mp3_buf = io.BytesIO()
        comm = edge_tts.Communicate(
            text,
            voice=self.voice,
            rate=self.rate,
            pitch=self.pitch,
            volume=self.volume,
        )
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                mp3_buf.write(chunk["data"])

        mp3_bytes = mp3_buf.getvalue()
        if not mp3_bytes:
            logger.warning("edge-tts returned no audio for {!r}", text[:50])
            return

        decoded = miniaudio.decode(
            mp3_bytes,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sample_rate=self.target_sample_rate,
        )

        yield AudioChunk(
            pcm=bytes(decoded.samples),
            sample_rate=decoded.sample_rate,
            channels=1,
        )
