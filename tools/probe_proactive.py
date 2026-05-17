"""Probe the proactive eval pipeline: real screen capture + Gemini Flash JSON decision."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from core.brain import Router  # noqa: E402
from core.memory import MemoryStore  # noqa: E402
from core.perception import Capture, get_active_window_title, get_idle_seconds  # noqa: E402
from core.persona import Persona  # noqa: E402
from core.session import ChatSession  # noqa: E402


async def main() -> int:
    with open("config.example.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["memory"]["db_path"] = "./data/proactive_probe.sqlite"
    if os.path.exists(cfg["memory"]["db_path"]):
        os.remove(cfg["memory"]["db_path"])

    router = Router.from_config(cfg)
    memory = MemoryStore.from_config(cfg, router=router)
    persona = Persona.from_config(cfg)
    session = ChatSession(router=router, memory=memory, persona=persona)
    capture = Capture(max_edge=1024)

    context = {
        "window_title": get_active_window_title(),
        "idle_seconds": int(get_idle_seconds()),
        "triggers": ["manual_probe"],
    }
    print(f"context: {context}")

    comment = await session.evaluate_and_speak(capture, context)
    print()
    if comment is None:
        print("verdict: SILENT (she chose not to speak)")
    else:
        print(f"verdict: SPOKE → {comment!r}")

    memory.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
