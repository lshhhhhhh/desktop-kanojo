"""Headless smoke test: construct the window, render for 3 seconds, exit clean.

Verifies:
- qasync event loop integration
- All UI widgets construct without error
- Backend wiring (Router/Memory/Session) succeeds
- No exceptions during the first paint cycle
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import qasync
import yaml
from dotenv import load_dotenv
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.window import CompanionWindow  # noqa: E402
from core.brain import Router  # noqa: E402
from core.memory import MemoryStore  # noqa: E402
from core.session import ChatSession  # noqa: E402


def main() -> int:
    load_dotenv()
    with open("config.example.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["memory"]["db_path"] = "./data/smoke_ui.sqlite"

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    router = Router.from_config(cfg)
    memory = MemoryStore.from_config(cfg, router=router)
    session = ChatSession(router=router, memory=memory)

    win = CompanionWindow(cfg, session=session)
    win.show()

    QTimer.singleShot(3000, app.quit)

    with loop:
        loop.run_forever()
    print("smoke_ui: exited cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
