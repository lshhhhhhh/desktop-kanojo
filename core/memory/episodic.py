from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .embed import Embedder


@dataclass
class Episode:
    id: int
    ts: str
    speaker: str
    text: str
    session_id: str | None = None
    importance: float = 0.5


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _vec_bytes(arr: np.ndarray) -> bytes:
    return np.asarray(arr, dtype=np.float32).tobytes()


class EpisodicStore:
    """L2: timestamped conversation events with vector retrieval.

    Retrieval scoring follows Generative Agents (Park et al. 2023):
    composite = similarity + recency_weight * recency + importance_weight * importance.
    """

    def __init__(self, conn: sqlite3.Connection, embedder: Embedder) -> None:
        self.conn = conn
        self.embedder = embedder

    async def add(
        self,
        speaker: str,
        text: str,
        session_id: str | None = None,
        importance: float = 0.5,
    ) -> Episode:
        ts = _now_iso()
        cur = self.conn.execute(
            "INSERT INTO episodes(ts, speaker, text, session_id, importance) "
            "VALUES(?,?,?,?,?)",
            (ts, speaker, text, session_id, importance),
        )
        ep_id = cur.lastrowid
        vec = await self.embedder.embed_one(text)
        self.conn.execute(
            "INSERT INTO episodes_vec(episode_id, embedding) VALUES(?, ?)",
            (ep_id, _vec_bytes(vec)),
        )
        self.conn.commit()
        return Episode(
            id=ep_id,
            ts=ts,
            speaker=speaker,
            text=text,
            session_id=session_id,
            importance=importance,
        )

    async def search(
        self,
        query: str,
        top_k: int = 5,
        time_decay_days: float = 30.0,
        recency_weight: float = 0.3,
        importance_weight: float = 0.2,
    ) -> list[tuple[Episode, float]]:
        q_vec = await self.embedder.embed_one(query)
        knn_k = max(top_k * 3, 10)
        rows = self.conn.execute(
            """
            SELECT e.id, e.ts, e.speaker, e.text, e.session_id, e.importance,
                   ev.distance
            FROM episodes_vec ev
            JOIN episodes e ON e.id = ev.episode_id
            WHERE ev.embedding MATCH ? AND k = ?
              AND e.archived = 0
            ORDER BY ev.distance
            """,
            (_vec_bytes(q_vec), knn_k),
        ).fetchall()

        now = datetime.now(UTC)
        scored: list[tuple[Episode, float]] = []
        for r in rows:
            # vec0 with distance_metric=cosine returns cosine distance in [0, 2];
            # convert to similarity in [-1, 1] then clip to [0, 1]
            dist = float(r["distance"])
            sim = max(0.0, 1.0 - dist)
            ep_ts = datetime.fromisoformat(r["ts"])
            age_days = (now - ep_ts).total_seconds() / 86400.0
            recency = math.exp(-age_days / time_decay_days)
            importance = float(r["importance"])
            composite = sim + recency_weight * recency + importance_weight * importance
            scored.append((
                Episode(
                    id=r["id"],
                    ts=r["ts"],
                    speaker=r["speaker"],
                    text=r["text"],
                    session_id=r["session_id"],
                    importance=importance,
                ),
                composite,
            ))
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:top_k]

        if top:
            ids = [(_now_iso(), ep.id) for ep, _ in top]
            self.conn.executemany(
                "UPDATE episodes SET referenced_count = referenced_count + 1, "
                "last_referenced_at = ? WHERE id = ?",
                ids,
            )
            self.conn.commit()
        return top

    def recent(self, limit: int = 20) -> list[Episode]:
        rows = self.conn.execute(
            "SELECT id, ts, speaker, text, session_id, importance FROM episodes "
            "WHERE archived = 0 ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            Episode(
                id=r["id"],
                ts=r["ts"],
                speaker=r["speaker"],
                text=r["text"],
                session_id=r["session_id"],
                importance=r["importance"],
            )
            for r in rows
        ]

    def list_since(self, episode_id: int) -> list[Episode]:
        rows = self.conn.execute(
            "SELECT id, ts, speaker, text, session_id, importance FROM episodes "
            "WHERE id > ? AND archived = 0 ORDER BY id ASC",
            (episode_id,),
        ).fetchall()
        return [
            Episode(
                id=r["id"],
                ts=r["ts"],
                speaker=r["speaker"],
                text=r["text"],
                session_id=r["session_id"],
                importance=r["importance"],
            )
            for r in rows
        ]

    def count(self) -> int:
        (n,) = self.conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE archived = 0"
        ).fetchone()
        return int(n)
