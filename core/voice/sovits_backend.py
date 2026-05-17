from __future__ import annotations

import asyncio
import queue as thread_queue
import threading
from collections.abc import AsyncIterator

import httpx
import miniaudio
from loguru import logger

from .base import AudioChunk, TTSBackend


class GPTSoVITSBackend(TTSBackend):
    """GPT-SoVITS v2/v3/v4 HTTP API client (RVC-Boss/GPT-SoVITS api_v2.py).

    Defaults assume the server is running at http://127.0.0.1:9880 with the
    target model already loaded. The reference audio + its transcript must
    correspond to the trained voice — see docs.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:9880",
        ref_audio: str = "",
        ref_text: str = "",
        ref_lang: str = "zh",
        text_lang: str = "zh",
        sample_rate: int = 48000,
        media_type: str = "raw",          # raw = headerless int16 PCM (best for streaming)
        timeout_s: float = 120.0,
        top_k: int = 5,
        top_p: float = 1.0,
        temperature: float = 1.0,
        speed_factor: float = 1.0,
        streaming_mode: int = 3,          # 0=off, 1=best quality slowest, 3=fastest
        min_chunk_length: int = 16,       # smaller = lower latency, more overhead
        overlap_length: int = 2,
        chunk_yield_bytes: int = 9600,    # bytes per AudioChunk (~100ms at 48kHz int16)
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ref_audio = ref_audio
        self.ref_text = ref_text
        self.ref_lang = ref_lang
        self.text_lang = text_lang
        self.sample_rate = sample_rate
        self.media_type = media_type
        self.timeout_s = timeout_s
        self.top_k = top_k
        self.top_p = top_p
        self.temperature = temperature
        self.speed_factor = speed_factor
        self.streaming_mode = streaming_mode
        self.min_chunk_length = min_chunk_length
        self.overlap_length = overlap_length
        self.chunk_yield_bytes = chunk_yield_bytes

    @classmethod
    def from_config(cls, cfg: dict) -> "GPTSoVITSBackend":
        return cls(
            base_url=cfg.get("base_url", "http://127.0.0.1:9880"),
            ref_audio=cfg.get("ref_audio", ""),
            ref_text=cfg.get("ref_text", ""),
            ref_lang=cfg.get("ref_lang", "zh"),
            text_lang=cfg.get("text_lang", "zh"),
            sample_rate=int(cfg.get("sample_rate", 48000)),
            media_type=cfg.get("media_type", "raw"),
            timeout_s=float(cfg.get("timeout_s", 120.0)),
            top_k=int(cfg.get("top_k", 5)),
            top_p=float(cfg.get("top_p", 1.0)),
            temperature=float(cfg.get("temperature", 1.0)),
            speed_factor=float(cfg.get("speed_factor", 1.0)),
            streaming_mode=int(cfg.get("streaming_mode", 3)),
            min_chunk_length=int(cfg.get("min_chunk_length", 16)),
            overlap_length=int(cfg.get("overlap_length", 2)),
            chunk_yield_bytes=int(cfg.get("chunk_yield_bytes", 9600)),
        )

    async def speak(self, text: str) -> AsyncIterator[AudioChunk]:
        text = text.strip()
        if not text:
            return
        if not self.ref_audio or not self.ref_text:
            logger.warning(
                "gpt-sovits backend has no ref_audio/ref_text configured; skipping speak"
            )
            return

        # Why sync httpx in a thread instead of async httpx?
        # qasync + nested `async with httpx.AsyncClient/Client.stream` triggers
        # "Attempted to exit cancel scope in a different task" errors from
        # anyio's cancel scopes when the async generator is GC'd outside its
        # original task context (which happens routinely under Qt event-loop
        # scheduling). Running the HTTP lifecycle in a real thread sidesteps
        # all of anyio's task-aware machinery while still streaming.
        q: thread_queue.Queue = thread_queue.Queue(maxsize=32)
        stop = threading.Event()
        loop = asyncio.get_running_loop()
        thread = threading.Thread(
            target=self._produce_sync, args=(text, q, stop), daemon=True
        )
        thread.start()
        try:
            while True:
                item = await loop.run_in_executor(None, q.get)
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            stop.set()
            # drain quickly so the producer thread can exit if it's blocked on put
            try:
                while True:
                    q.get_nowait()
            except thread_queue.Empty:
                pass

    def _produce_sync(
        self,
        text: str,
        q: thread_queue.Queue,
        stop: threading.Event,
    ) -> None:
        payload = {
            "text": text,
            "text_lang": self.text_lang,
            "ref_audio_path": self.ref_audio,
            "prompt_text": self.ref_text,
            "prompt_lang": self.ref_lang,
            "media_type": self.media_type,
            "streaming_mode": self.streaming_mode,
            "min_chunk_length": self.min_chunk_length,
            "overlap_length": self.overlap_length,
            "top_k": self.top_k,
            "top_p": self.top_p,
            "temperature": self.temperature,
            "speed_factor": self.speed_factor,
        }
        url = f"{self.base_url}/tts"

        def put(item) -> bool:
            """Put with cancellation support. Returns False if we should stop."""
            while not stop.is_set():
                try:
                    q.put(item, timeout=0.1)
                    return True
                except thread_queue.Full:
                    continue
            return False

        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout_s)) as client:
                with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = resp.read()
                        logger.warning(
                            "gpt-sovits HTTP {}: {}",
                            resp.status_code,
                            body[:400].decode("utf-8", errors="replace"),
                        )
                        return

                    if self.media_type == "raw":
                        buf = bytearray()
                        target = self.chunk_yield_bytes
                        if target % 2:
                            target -= 1
                        for raw in resp.iter_bytes(chunk_size=4096):
                            if stop.is_set():
                                return
                            if not raw:
                                continue
                            buf.extend(raw)
                            while len(buf) >= target:
                                out = bytes(buf[:target])
                                del buf[:target]
                                if not put(
                                    AudioChunk(
                                        pcm=out,
                                        sample_rate=self.sample_rate,
                                        channels=1,
                                    )
                                ):
                                    return
                        if buf and not stop.is_set():
                            if len(buf) % 2:
                                buf.pop()
                            if buf:
                                put(
                                    AudioChunk(
                                        pcm=bytes(buf),
                                        sample_rate=self.sample_rate,
                                        channels=1,
                                    )
                                )
                    else:
                        body = resp.read()
                        if body:
                            decoded = miniaudio.decode(
                                body,
                                output_format=miniaudio.SampleFormat.SIGNED16,
                                nchannels=1,
                                sample_rate=self.sample_rate,
                            )
                            put(
                                AudioChunk(
                                    pcm=bytes(decoded.samples),
                                    sample_rate=decoded.sample_rate,
                                    channels=1,
                                )
                            )
        except Exception as e:
            logger.warning("gpt-sovits stream error: {}", e)
        finally:
            try:
                q.put(None, timeout=1.0)
            except thread_queue.Full:
                pass
