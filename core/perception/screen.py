from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from datetime import UTC, datetime

import mss
from loguru import logger
from PIL import Image


@dataclass
class ScreenObservation:
    """A single screen capture, normalized + ready for VLM consumption."""

    ts: str            # ISO timestamp
    width: int
    height: int
    image_b64: str     # base64-encoded PNG, no data: prefix
    monitor_index: int
    mime: str = "image/png"


class Capture:
    """Screen capture utility built on python-mss.

    Captures the primary monitor by default, downsamples to a max edge length,
    and returns a base64 PNG suitable for sending to Gemini / GPT vision.
    """

    def __init__(self, max_edge: int = 1024, monitor_index: int = 0) -> None:
        # mss.monitors[0] = bounding box of ALL monitors stitched together.
        # Index 1+ = individual monitors. Default 0 = capture everything.
        self.max_edge = max_edge
        self.monitor_index = monitor_index

    def list_monitors(self) -> list[dict]:
        """Return mss's monitor list: index 0 = all stitched, 1+ = individual."""
        with mss.mss() as sct:
            return list(sct.monitors)

    def grab(self, monitor_index: int | None = None) -> ScreenObservation:
        idx = monitor_index if monitor_index is not None else self.monitor_index
        with mss.mss() as sct:
            if idx >= len(sct.monitors):
                logger.warning("monitor {} not found, falling back to all", idx)
                idx = 0
            mon = sct.monitors[idx]
            raw = sct.grab(mon)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        orig_w, orig_h = img.size
        long_edge = max(orig_w, orig_h)
        if long_edge > self.max_edge:
            scale = self.max_edge / long_edge
            new_size = (int(orig_w * scale), int(orig_h * scale))
            img = img.resize(new_size, Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        png_bytes = buf.getvalue()

        b64 = base64.b64encode(png_bytes).decode("ascii")
        logger.debug(
            "screen captured: monitor={} orig={}x{} sent={}x{} png={}KB",
            idx, orig_w, orig_h, img.size[0], img.size[1], len(png_bytes) // 1024,
        )
        return ScreenObservation(
            ts=datetime.now(UTC).isoformat(),
            width=img.size[0],
            height=img.size[1],
            image_b64=b64,
            monitor_index=idx,
        )
