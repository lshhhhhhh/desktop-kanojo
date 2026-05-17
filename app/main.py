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
from core import preferences
from core.brain import Router
from core.memory import MemoryStore
from core.persona import Persona
from core.session import ChatSession


def load_config() -> dict:
    load_dotenv()
    cwd = Path.cwd()
    example_path = cwd / "config.example.yaml"
    user_path = cwd / "config.yaml"

    example: dict | None = None
    if example_path.exists():
        with example_path.open("r", encoding="utf-8") as f:
            example = yaml.safe_load(f) or {}

    if user_path.exists():
        logger.info("Loading config from {}", user_path)
        with user_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if example is not None:
            _merge_new_keys_from_example(cfg, example)
        return cfg

    if example is not None:
        logger.info("Loading config from {}", example_path)
        return example

    raise FileNotFoundError("config.yaml or config.example.yaml not found in cwd")


def _apply_voice_overrides(cfg: dict) -> None:
    """Merge preferences.yaml's voice_overrides into cfg['voice'].

    The user edits voice settings in the settings dialog; persisting those
    to config.yaml would clobber its comments. Keeping them in preferences
    and overlaying at startup is the same pattern we use for chat_backend
    and live2d_active_model.

    Nested keys (edge_tts, sovits) are merged one level deep so the user
    can override just `voice` without losing other edge_tts params.
    """
    from core import preferences

    overrides = preferences.get_voice_overrides()
    if not overrides:
        return
    voice = cfg.setdefault("voice", {})
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(voice.get(k), dict):
            voice[k] = {**voice[k], **v}
        else:
            voice[k] = v


def _merge_new_keys_from_example(user_cfg: dict, example_cfg: dict) -> None:
    """Pull in newly-shipped backends from config.example.yaml that the
    user's config.yaml predates (zhipu, qwen-vl, future additions). Only
    adds — never overwrites — so users can still customize / remove
    backends and the change survives.

    Same idea for `brain.routing`: if the example sets a route the user
    hasn't, copy it in. This keeps a forked config.yaml from going stale
    against later releases that introduce new routing intents."""
    user_brain = user_cfg.setdefault("brain", {})
    example_brain = example_cfg.get("brain") or {}

    user_backends = user_brain.setdefault("backends", {})
    added_backends = []
    patched_backends = []
    for name, ex_b in (example_brain.get("backends") or {}).items():
        if name not in user_backends:
            user_backends[name] = ex_b
            added_backends.append(name)
        else:
            # Existing backend: fill in any new keys the example added since
            # this user's config.yaml was last copied. Common case: a new
            # flag like `uses_max_completion_tokens` showed up in a release
            # and the user's older config lacks it. We never overwrite an
            # existing key; only fill missing ones.
            user_b = user_backends[name]
            for k, v in ex_b.items():
                if k not in user_b:
                    user_b[k] = v
                    patched_backends.append(f"{name}.{k}")
    if added_backends:
        logger.info("merged new backends from example: {}", added_backends)
    if patched_backends:
        logger.info("backfilled backend fields from example: {}", patched_backends)

    user_routing = user_brain.setdefault("routing", {})
    example_routing = example_brain.get("routing") or {}
    for intent, target in example_routing.items():
        if intent not in user_routing and target in user_backends:
            user_routing[intent] = target


def main() -> int:
    cfg = load_config()
    # Apply user-edited voice settings from the UI before any code reads
    # cfg["voice"]. Shallow merge so a saved backend/voice/rate from the
    # settings dialog wins over config.example defaults; nested dicts
    # (edge_tts:, sovits:) are merged one level deep.
    _apply_voice_overrides(cfg)

    app = QApplication(sys.argv)
    app.setApplicationName("imouto")

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    router = Router.from_config(cfg)
    # Apply the user-overridden default chat backend from preferences.yaml,
    # if any. Set in the UI ("模型" tab). Falls back to config when unset or
    # when the saved backend no longer exists in config.
    saved_backend = preferences.get_chat_backend()
    if saved_backend and saved_backend in router.backends:
        router.default = saved_backend
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
