from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import qasync
import yaml
from dotenv import load_dotenv
from loguru import logger
from PySide6.QtWidgets import QApplication

from app.window import CompanionWindow
from core.brain import Router
from core.memory import MemoryStore
from core.persona import Persona
from core.session import ChatSession


def load_config() -> dict:
    load_dotenv()
    cwd = Path.cwd()
    for candidate in (cwd / "config.yaml", cwd / "config.example.yaml"):
        if candidate.exists():
            logger.info("Loading config from {}", candidate)
            with candidate.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    raise FileNotFoundError("config.yaml or config.example.yaml not found in cwd")


def main() -> int:
    cfg = load_config()
    app = QApplication(sys.argv)
    app.setApplicationName("imouto")

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    router = Router.from_config(cfg)
    memory = MemoryStore.from_config(cfg, router=router)
    persona = Persona.from_config(cfg)
    session = ChatSession(router=router, memory=memory, persona=persona)

    win = CompanionWindow(cfg, session=session)
    win.show()

    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
