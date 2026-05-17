from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.brain import Router  # noqa: E402
from core.memory import MemoryStore  # noqa: E402
from core.perception import Capture  # noqa: E402
from core.persona import Persona  # noqa: E402
from core.session import ChatSession  # noqa: E402


def load_config() -> dict:
    load_dotenv()
    cwd = Path.cwd()
    for candidate in (cwd / "config.yaml", cwd / "config.example.yaml"):
        if candidate.exists():
            with candidate.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    raise FileNotFoundError("no config.yaml or config.example.yaml in cwd")


async def main() -> int:
    cfg = load_config()
    router = Router.from_config(cfg)
    memory = MemoryStore.from_config(cfg, router=router)
    persona = Persona.from_config(cfg)
    session = ChatSession(router=router, memory=memory, persona=persona)

    backend = router.select()
    capture = Capture(max_edge=1024)
    print(f"imouto REPL — session {session.session_id} — backend {backend.name} ({backend.model})")
    print("commands: /quit, /reflect, /facts, /recent, /search <query>, /see [prompt]")
    print("-" * 60)

    while True:
        try:
            user_text = input("\n你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_text:
            continue
        if user_text == "/quit":
            break
        if user_text == "/reflect":
            await memory.run_reflection()
            print("[reflection done]")
            continue
        if user_text == "/facts":
            facts = memory.facts.all_active()
            if not facts:
                print("  (no facts yet)")
            for f in facts:
                print(f"  {f.key}: {f.value} (conf={f.confidence:.2f})")
            continue
        if user_text == "/recent":
            for ep in memory.episodic.recent(limit=10):
                preview = ep.text.replace("\n", " ")[:80]
                print(f"  #{ep.id} [{ep.speaker}] {preview}")
            continue
        if user_text.startswith("/search "):
            q = user_text[len("/search "):].strip()
            if not q:
                continue
            results = await memory.episodic.search(q, top_k=5)
            for ep, score in results:
                preview = ep.text.replace("\n", " ")[:80]
                print(f"  [{score:.3f}] #{ep.id} [{ep.speaker}] {preview}")
            continue
        if user_text == "/see" or user_text.startswith("/see "):
            prompt = user_text[len("/see "):].strip() if user_text.startswith("/see ") else None
            print("妹 (看屏) > ", end="", flush=True)
            try:
                async for chunk in session.see_screen(capture, user_text=prompt):
                    print(chunk.delta, end="", flush=True)
                print()
            except Exception as e:
                print(f"\n[error: {e}]")
                logger.exception("screenshot failed")
            continue

        print("妹 > ", end="", flush=True)
        try:
            async for chunk in session.chat(user_text):
                print(chunk.delta, end="", flush=True)
            print()
        except Exception as e:
            print(f"\n[error: {e}]")
            logger.exception("chat failed")

    memory.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
