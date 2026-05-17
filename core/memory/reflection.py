from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from loguru import logger

from core.brain import ChatRequest, Message

if TYPE_CHECKING:
    from core.brain import Router

    from .episodic import Episode
    from .facts import FactStore


REFLECTION_PROMPT = """你是桌面伴侣的记忆整理助手。从下面这段最近对话里，提取关于**用户**的稳定事实，输出 JSON。

规则：
1. 只提取关于用户本身的客观事实，不要主观判断、情绪、临时状态或对话内容的转述
2. key 用点分层级的全小写英文命名，例如：
   - user.profile.name / user.profile.age / user.profile.location
   - user.pets.cat.name / user.pets.dog.breed
   - user.likes.<topic> / user.dislikes.<topic>
   - user.work.role / user.work.company / user.work.language
   - user.relationships.partner.name
3. value 用简短中文短语，不要完整句子
4. confidence 0.0-1.0，反映把握程度
5. 没有可提取的就输出空数组
6. 严格只输出 JSON，不要解释、不要 markdown 代码块

输出格式：
{
  "facts": [
    {"key": "user.pets.cat.name", "value": "阿黄", "confidence": 0.9}
  ]
}

对话片段：
"""


def _extract_json(text: str) -> dict | None:
    """Robust JSON extraction from LLM output (handles markdown fences, prose)."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # strip ```json ... ``` fences
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    # last-resort: first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


class Reflector:
    """Periodic LLM-driven fact extraction from recent episodes.

    Naming follows Park et al. 2023 ("Generative Agents"): a Reflector ingests a
    window of recent observations and produces higher-level structured insights
    (here, key-value facts persisted in `FactStore`).
    """

    def __init__(
        self,
        router: "Router",
        fact_store: "FactStore",
        intent: str = "reflection",
    ) -> None:
        self.router = router
        self.fact_store = fact_store
        self.intent = intent

    async def reflect(
        self,
        episodes: list["Episode"],
        max_retries: int = 3,
    ) -> list[dict]:
        if not episodes:
            return []
        backend = self.router.select(self.intent)
        transcript = "\n".join(f"[{ep.speaker}] {ep.text}" for ep in episodes)
        prompt = REFLECTION_PROMPT + transcript

        for attempt in range(max_retries):
            req = ChatRequest(
                messages=[Message.text("user", prompt)],
                temperature=0.2,
                stream=False,
            )
            text = ""
            try:
                async for chunk in backend.chat(req):
                    text += chunk.delta
            except Exception as e:
                logger.warning("reflection LLM call failed (attempt {}): {}", attempt + 1, e)
                continue

            data = _extract_json(text)
            if data is None:
                logger.warning(
                    "reflection attempt {} produced no JSON; raw[:200]={!r}",
                    attempt + 1,
                    text[:200],
                )
                continue

            # Accept both {"facts": [...]} and bare [...] top-level shapes.
            if isinstance(data, list):
                facts = data
            elif isinstance(data, dict):
                facts = data.get("facts", [])
            else:
                facts = []
            if not isinstance(facts, list):
                logger.warning("reflection got non-list facts: {!r}", facts)
                continue

            source_ep_id = episodes[-1].id
            written: list[dict] = []
            for f in facts:
                if not isinstance(f, dict):
                    continue
                key = str(f.get("key", "")).strip()
                value = str(f.get("value", "")).strip()
                try:
                    conf = float(f.get("confidence", 0.7))
                except (TypeError, ValueError):
                    conf = 0.7
                if not key or not value:
                    continue
                self.fact_store.upsert(
                    key=key,
                    value=value,
                    confidence=conf,
                    source_episode_id=source_ep_id,
                )
                written.append({"key": key, "value": value, "confidence": conf})
            logger.info(
                "reflection: extracted {} facts from {} episodes",
                len(written),
                len(episodes),
            )
            return written

        logger.warning("reflection failed after {} attempts", max_retries)
        return []
