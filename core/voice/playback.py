from __future__ import annotations

import asyncio
from collections.abc import Callable

import numpy as np
from loguru import logger
from PySide6.QtCore import QIODevice
from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSink

# Why QAudioSink and not sounddevice/PortAudio?
# When the app embeds a QWebEngineView (we do, for Live2D), Chromium spawns
# audio-service helper processes that take over the Windows audio routing for
# the whole Qt process. PortAudio's MME/WASAPI/DSOUND streams open silently
# but produce no output. Qt's own QAudioSink shares Qt's audio backend so it
# coexists with QtWebEngine. It also has zero extra dependencies (ships with
# PySide6) and works on Windows/macOS/Linux.


def _make_sink(
    sample_rate: int,
    channels: int,
    device: QAudioDevice | None = None,
) -> QAudioSink:
    fmt = QAudioFormat()
    fmt.setSampleRate(sample_rate)
    fmt.setChannelCount(channels)
    fmt.setSampleFormat(QAudioFormat.Int16)
    sink = QAudioSink(device, fmt) if device is not None else QAudioSink(fmt)
    # Larger ring buffer reduces underrun glitches at sentence boundaries.
    # 400 ms at 48kHz mono int16 = ~38 KB; cheap.
    sink.setBufferSize(int(0.4 * sample_rate * channels * 2))
    return sink


class SentencePlayer:
    """Streaming player for a single TTS sentence.

    Built around QAudioSink in push mode: one sink per sentence, multiple PCM
    chunks are appended without tearing the audio stream down between them.
    Per-chunk open/close (the previous approach) caused audible ~50 ms gaps
    between every chunk; with push mode the audio is gapless.

    Envelope (RMS) sampling is wall-clock-aligned to total frames pushed so
    Live2D mouth tracking stays in sync with what's actually playing.
    """

    def __init__(
        self,
        on_envelope: Callable[[float], None] | None = None,
        *,
        envelope_window_ms: int = 50,
        envelope_gain: float = 3.5,
        envelope_floor: float = 0.0,
        audio_device: QAudioDevice | None = None,
    ) -> None:
        self._on_envelope = on_envelope
        self._envelope_window_ms = envelope_window_ms
        self._envelope_gain = envelope_gain
        self._envelope_floor = envelope_floor
        self._audio_device = audio_device

        self._sink: QAudioSink | None = None
        self._io: QIODevice | None = None
        self._sample_rate: int = 0
        self._channels: int = 1
        self._loop = asyncio.get_event_loop()
        self._start_time: float | None = None
        self._frames_pushed: int = 0

    async def feed(self, pcm_bytes: bytes, sample_rate: int, channels: int = 1) -> None:
        if not pcm_bytes:
            return
        if self._sink is None:
            self._sample_rate = sample_rate
            self._channels = channels
            self._sink = _make_sink(sample_rate, channels, self._audio_device)
            self._io = self._sink.start()  # push mode — returns QIODevice
            self._start_time = self._loop.time()

        await self._write_all(pcm_bytes)
        await self._drive_envelope(pcm_bytes)

    async def _write_all(self, data: bytes) -> None:
        assert self._io is not None and self._sink is not None
        offset = 0
        n = len(data)
        while offset < n:
            free = self._sink.bytesFree()
            if free <= 0:
                # buffer full — give it a tick to drain
                await asyncio.sleep(0.01)
                continue
            take = min(free, n - offset)
            self._io.write(data[offset : offset + take])
            offset += take

    async def _drive_envelope(self, chunk_bytes: bytes) -> None:
        samples = np.frombuffer(chunk_bytes, dtype=np.int16)
        if samples.size == 0:
            return
        sr = self._sample_rate
        samples_per_window = max(1, int(sr * self._envelope_window_ms / 1000))
        n = samples.size
        pos = 0
        assert self._start_time is not None
        while pos < n:
            window = samples[pos : pos + samples_per_window]
            f = window.astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(f * f))) if f.size else 0.0
            mouth = max(
                self._envelope_floor, min(1.0, rms * self._envelope_gain)
            )
            if self._on_envelope is not None:
                try:
                    self._on_envelope(mouth)
                except Exception:
                    logger.exception("on_envelope callback raised")
            step = min(samples_per_window, n - pos)
            pos += step
            self._frames_pushed += step
            target_t = self._start_time + self._frames_pushed / sr
            sleep_for = target_t - self._loop.time()
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    async def close(self) -> None:
        if self._on_envelope is not None:
            try:
                self._on_envelope(0.0)
            except Exception:
                pass
        if self._sink is None:
            return
        # Let any tail bytes in the Qt audio buffer drain before tearing down.
        await asyncio.sleep(0.1)
        try:
            self._sink.stop()
        except Exception:
            pass
        self._sink = None
        self._io = None
