"""Smoke + audible test for the voice pipeline.

Runs three things:
1. SentenceBuffer unit assertions (no audio)
2. EdgeTTSBackend → confirms MP3 decode produces sane PCM (no audio)
3. Full pipeline: Speaker plays a sentence, calls on_mouth callback (audible!)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.voice import EdgeTTSBackend, SentenceBuffer, Speaker  # noqa: E402


def test_splitter() -> None:
    buf = SentenceBuffer()
    out = buf.feed("你好。我是")
    assert out == ["你好。"], f"got {out!r}"
    out = buf.feed("小妹！")
    assert out == ["我是小妹！"], f"got {out!r}"
    out = buf.feed("今天天气真好")
    assert out == []
    rest = buf.flush()
    assert rest == "今天天气真好", f"got {rest!r}"
    print("[splitter] OK")


async def test_decode() -> None:
    be = EdgeTTSBackend()
    chunks = []
    async for c in be.speak("你好，我是小妹。"):
        chunks.append(c)
    total = sum(len(c.pcm) for c in chunks)
    sr = chunks[0].sample_rate if chunks else None
    print(f"[decode] {len(chunks)} chunk, {total} bytes pcm, sample_rate={sr}")
    assert chunks, "no audio chunks"
    assert sr == 24000, f"unexpected sample rate: {sr}"


async def test_speak_audible() -> None:
    print("[audible] now playing test sentence — listen for it!")
    be = EdgeTTSBackend()
    mouth_log = []

    def on_mouth(v: float) -> None:
        mouth_log.append(v)

    sp = Speaker(be, on_mouth=on_mouth)
    sp.start()
    sp.enqueue("你好啊，我是小妹。今天过得怎么样？")
    sp.enqueue("怎么不说话，是不是被我萌到了。")
    # wait for queue to drain (~5-6s)
    await asyncio.sleep(8)
    sp.stop()
    await asyncio.sleep(0.5)
    print(f"[audible] {len(mouth_log)} envelope samples, max={max(mouth_log, default=0):.3f}")


async def main() -> int:
    test_splitter()
    await test_decode()
    await test_speak_audible()
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
