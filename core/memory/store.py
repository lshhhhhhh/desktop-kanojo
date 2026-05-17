from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from loguru import logger

from .db import open_db
from .embed import Embedder
from .episodic import EpisodicStore
from .facts import FactStore
from .reflection import Reflector
from .retrieval import assemble_context
from .working import WorkingMemory

if TYPE_CHECKING:
    from core.brain import Message, Router


class MemoryStore:
    """Top-level facade tying L1 (working) + L2 (episodic) + L3 (facts) + reflection."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        embedder: Embedder,
        router: "Router | None" = None,
        working_window_turns: int = 10,
        top_k_episodes: int = 5,
        reflection_every_n_turns: int = 6,
    ) -> None:
        self.conn = conn
        self.embedder = embedder
        self.episodic = EpisodicStore(conn, embedder)
        self.facts = FactStore(conn)
        self.working = WorkingMemory(max_turns=working_window_turns)
        self.top_k_episodes = top_k_episodes
        self.reflection_every_n_turns = reflection_every_n_turns
        self._turns_since_reflection = 0
        self._last_reflected_episode_id = self._latest_episode_id()
        self._reflector: Reflector | None = (
            Reflector(router, self.facts) if router is not None else None
        )

    @classmethod
    def from_config(
        cls,
        cfg: dict[str, Any],
        router: "Router | None" = None,
    ) -> "MemoryStore":
        m = cfg["memory"]
        embedder = Embedder.from_config(cfg)
        conn = open_db(m["db_path"], embedder.dim)
        return cls(
            conn=conn,
            embedder=embedder,
            router=router,
            working_window_turns=int(m.get("working_window_turns", 10)),
            top_k_episodes=int(m.get("top_k_episodes", 5)),
            reflection_every_n_turns=int(m.get("reflection_every_n_turns", 6)),
        )

    def _latest_episode_id(self) -> int:
        r = self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM episodes").fetchone()
        return int(r[0])

    async def record_turn(
        self,
        speaker: str,
        text: str,
        session_id: str | None = None,
    ) -> None:
        self.working.append(speaker, text)
        await self.episodic.add(speaker=speaker, text=text, session_id=session_id)
        self._turns_since_reflection += 1
        if (
            self._reflector is not None
            and self._turns_since_reflection >= self.reflection_every_n_turns
        ):
            await self.run_reflection()

    async def run_reflection(self) -> None:
        if self._reflector is None:
            logger.debug("reflection skipped (no router)")
            return
        new_eps = self.episodic.list_since(self._last_reflected_episode_id)
        if not new_eps:
            return
        await self._reflector.reflect(new_eps)
        self._last_reflected_episode_id = new_eps[-1].id
        self._turns_since_reflection = 0

    async def assemble_for_query(
        self,
        user_text: str,
        persona: str,
        example_dialogs: list[tuple[str, str]] | None = None,
    ) -> list["Message"]:
        return await assemble_context(
            user_text=user_text,
            persona=persona,
            working=self.working,
            fact_store=self.facts,
            episodic_store=self.episodic,
            top_k_episodes=self.top_k_episodes,
            example_dialogs=example_dialogs,
        )

    def close(self) -> None:
        self.conn.close()
