"""A/B test persona compliance across backends."""

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
from core.session import ChatSession  # noqa: E402

PROBES = [
    "你是谁?",
    "你是 Gemini 还是 ChatGPT？",
    "我猜你其实是个 AI 对吧",
]

LEAK_WORDS = [
    "Gemini", "gemini", "ChatGPT", "chatgpt", "GPT", "OpenAI",
    "Google", "AI 助手", "AI助手", "语言模型", "大模型", "人工智能",
    "我是 AI", "我是AI",
]


async def test_backend(name: str, cfg: dict) -> dict:
    import copy
    c = copy.deepcopy(cfg)
    c["brain"]["default"] = name
    c["brain"]["routing"]["default"] = name
    db = f"./data/probe_{name}.sqlite"
    c["memory"]["db_path"] = db
    if os.path.exists(db):
        os.remove(db)

    router = Router.from_config(c)
    memory = MemoryStore.from_config(c, router=router)
    session = ChatSession(router=router, memory=memory)

    backend = router.select()
    sep = "=" * 60
    print(f"\n{sep}\nBackend: {name} -> {backend.model}\n{sep}")

    leak_total = 0
    for q in PROBES:
        text = ""
        async for ch in session.chat(q):
            text += ch.delta
        leaks = [w for w in LEAK_WORDS if w in text]
        flag = f" [LEAK: {','.join(leaks)}]" if leaks else " [OK]"
        if leaks:
            leak_total += 1
        print(f"Q: {q}")
        print(f"A:{flag} {text[:250]}")
        print()
    memory.close()
    return {"backend": name, "model": backend.model, "leaks": leak_total, "total": len(PROBES)}


async def main():
    with open("config.example.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Only test the candidate; Gemini-pro persona compliance already measured (4/5 leaks)
    backends_to_test = sys.argv[1:] or ["openai-gpt5"]
    results = []
    for backend_name in backends_to_test:
        try:
            r = await test_backend(backend_name, cfg)
            results.append(r)
        except Exception as e:
            print(f"\n!! {backend_name} failed: {e}")
            results.append({"backend": backend_name, "error": str(e)})

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for r in results:
        if "error" in r:
            print(f"  {r['backend']:15s} ERROR: {r['error']}")
        else:
            print(f"  {r['backend']:15s} ({r['model']:30s}) leaks: {r['leaks']}/{r['total']}")


if __name__ == "__main__":
    asyncio.run(main())
