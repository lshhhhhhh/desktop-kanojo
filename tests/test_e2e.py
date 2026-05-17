"""End-to-end tests against the real Gemini API.

Skipped automatically when GEMINI_API_KEY is not set.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from dotenv import load_dotenv

from core.brain import Router
from core.memory import MemoryStore
from core.session import ChatSession

load_dotenv()


pytestmark = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)


def _load_cfg() -> dict:
    with open("config.example.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # config.example defaults to deepseek-chat (zero-config path for China).
    # The e2e suite is gated on GEMINI_API_KEY (embedding + cheap chat), so
    # override the chat default to keep these tests self-consistent with
    # what's actually available.
    cfg["brain"]["default"] = "gemini-flash"
    cfg["brain"]["routing"]["default"] = "gemini-flash"
    cfg["brain"]["routing"]["reflection"] = "gemini-flash"
    return cfg


@pytest.mark.asyncio
async def test_embedding_roundtrip(tmp_path: Path):
    cfg = _load_cfg()
    cfg["memory"]["db_path"] = str(tmp_path / "m.sqlite")
    router = Router.from_config(cfg)
    memory = MemoryStore.from_config(cfg, router=router)
    try:
        await memory.episodic.add("user", "我养了一只橘猫叫阿黄")
        await memory.episodic.add("user", "今天去爬山了，累死")
        await memory.episodic.add("user", "Python 3.13 的 free-threaded build 看起来很有意思")
        results = await memory.episodic.search("我的宠物", top_k=2)
        assert results, "search returned no results"
        top_text = results[0][0].text
        assert "阿黄" in top_text or "猫" in top_text, f"unexpected top hit: {top_text!r}"
    finally:
        memory.close()


@pytest.mark.asyncio
async def test_chat_basic(tmp_path: Path):
    cfg = _load_cfg()
    cfg["memory"]["db_path"] = str(tmp_path / "m.sqlite")
    router = Router.from_config(cfg)
    memory = MemoryStore.from_config(cfg, router=router)
    session = ChatSession(router=router, memory=memory)
    try:
        full = ""
        async for chunk in session.chat("你好"):
            full += chunk.delta
        assert full.strip(), "empty response"
    finally:
        memory.close()


@pytest.mark.asyncio
async def test_5_turn_with_reflection(tmp_path: Path):
    """5 turns of self-disclosure → reflection → assert facts extracted + recall."""
    cfg = _load_cfg()
    cfg["memory"]["db_path"] = str(tmp_path / "m.sqlite")
    router = Router.from_config(cfg)
    memory = MemoryStore.from_config(cfg, router=router)
    session = ChatSession(router=router, memory=memory)

    convo = [
        "嗨，我叫小赖",
        "我养了一只猫叫阿黄，是只大橘子",
        "我是程序员，主要写 Python",
        "我住在杭州西湖区",
        "我喜欢喝美式咖啡，不加糖",
    ]

    try:
        for line in convo:
            full = ""
            async for chunk in session.chat(line):
                full += chunk.delta
            assert full.strip(), f"empty response to: {line}"

        await memory.run_reflection()

        facts = memory.facts.all_active()
        keys = {f.key for f in facts}
        print("\nExtracted facts:")
        for f in facts:
            print(f"  {f.key}: {f.value} (conf={f.confidence:.2f})")
        assert len(facts) >= 3, f"expected >=3 facts, got {len(facts)}: {keys}"

        recall = await memory.episodic.search("我的宠物叫什么", top_k=3)
        recall_texts = [ep.text for ep, _ in recall]
        assert any("阿黄" in t or "橘" in t for t in recall_texts), (
            f"cat not recalled: {recall_texts}"
        )
    finally:
        memory.close()
