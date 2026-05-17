"""Smoke verification: imports, persona load, monitor enumeration."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from core.brain import Router  # noqa: E402, F401
from core.memory import MemoryStore  # noqa: E402, F401
from core.perception import Capture  # noqa: E402
from core.persona import Persona  # noqa: E402
from core.session import ChatSession  # noqa: E402, F401
from app.settings_dialog import SettingsDialog  # noqa: E402, F401
from app.window import CompanionWindow  # noqa: E402, F401


def main() -> int:
    print("all imports OK")

    with open("config.example.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    p = Persona.from_config(cfg)
    print(f"persona loaded: name={p.name!r} prefix={p.display_prefix!r} examples={len(p.examples)}")
    if p.examples:
        u, a = p.examples[0]
        print(f"  first example: {u!r} -> {a!r}")

    available = Persona.list_available(cfg["persona"]["path"])
    print(f"available personas: {available}")

    mons = Capture().list_monitors()
    print(f"monitors: {len(mons) - 1} individual + 1 stitched")
    for i, m in enumerate(mons):
        w = m["width"]
        h = m["height"]
        left = m["left"]
        top = m["top"]
        tag = "(all stitched)" if i == 0 else ""
        print(f"  [{i}] {w}x{h} at ({left},{top}) {tag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
