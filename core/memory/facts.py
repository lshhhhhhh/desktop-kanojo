from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class Fact:
    id: int
    key: str
    value: str
    confidence: float
    created_at: str
    updated_at: str
    referenced_count: int = 0
    last_referenced_at: str | None = None
    source_episode_id: int | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class FactStore:
    """L3: semantic facts about the user as structured key-value pairs.

    Supersession model: when a fact's value changes, the old row stays in the
    table with `superseded_by` pointing to the new row. Active facts are those
    with `superseded_by IS NULL`. Same-value upserts bump confidence instead.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(
        self,
        key: str,
        value: str,
        confidence: float = 1.0,
        source_episode_id: int | None = None,
        bump_step: float = 0.1,
    ) -> Fact:
        now = _now_iso()
        existing = self.conn.execute(
            "SELECT id, value, confidence FROM facts "
            "WHERE key = ? AND superseded_by IS NULL ORDER BY id DESC LIMIT 1",
            (key,),
        ).fetchone()

        if existing is None:
            cur = self.conn.execute(
                "INSERT INTO facts(key, value, confidence, created_at, updated_at, "
                "source_episode_id) VALUES(?,?,?,?,?,?)",
                (key, value, confidence, now, now, source_episode_id),
            )
            fact_id = cur.lastrowid
            final_conf = confidence
            self.conn.commit()
        elif existing["value"] == value:
            final_conf = min(1.0, existing["confidence"] + bump_step)
            self.conn.execute(
                "UPDATE facts SET confidence = ?, updated_at = ? WHERE id = ?",
                (final_conf, now, existing["id"]),
            )
            fact_id = existing["id"]
            self.conn.commit()
        else:
            cur = self.conn.execute(
                "INSERT INTO facts(key, value, confidence, created_at, updated_at, "
                "source_episode_id) VALUES(?,?,?,?,?,?)",
                (key, value, confidence, now, now, source_episode_id),
            )
            fact_id = cur.lastrowid
            self.conn.execute(
                "UPDATE facts SET superseded_by = ?, updated_at = ? WHERE id = ?",
                (fact_id, now, existing["id"]),
            )
            final_conf = confidence
            self.conn.commit()

        return Fact(
            id=fact_id,
            key=key,
            value=value,
            confidence=final_conf,
            created_at=now,
            updated_at=now,
            source_episode_id=source_episode_id,
        )

    def all_active(self) -> list[Fact]:
        rows = self.conn.execute(
            "SELECT id, key, value, confidence, created_at, updated_at, "
            "referenced_count, last_referenced_at, source_episode_id "
            "FROM facts WHERE superseded_by IS NULL "
            "ORDER BY confidence DESC, updated_at DESC"
        ).fetchall()
        return [
            Fact(
                id=r["id"],
                key=r["key"],
                value=r["value"],
                confidence=r["confidence"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                referenced_count=r["referenced_count"],
                last_referenced_at=r["last_referenced_at"],
                source_episode_id=r["source_episode_id"],
            )
            for r in rows
        ]

    def get(self, key: str) -> Fact | None:
        r = self.conn.execute(
            "SELECT id, key, value, confidence, created_at, updated_at, "
            "referenced_count, last_referenced_at, source_episode_id "
            "FROM facts WHERE key = ? AND superseded_by IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (key,),
        ).fetchone()
        if r is None:
            return None
        return Fact(
            id=r["id"],
            key=r["key"],
            value=r["value"],
            confidence=r["confidence"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            referenced_count=r["referenced_count"],
            last_referenced_at=r["last_referenced_at"],
            source_episode_id=r["source_episode_id"],
        )

    def mark_referenced(self, keys: list[str]) -> None:
        if not keys:
            return
        now = _now_iso()
        self.conn.executemany(
            "UPDATE facts SET referenced_count = referenced_count + 1, "
            "last_referenced_at = ? WHERE key = ? AND superseded_by IS NULL",
            [(now, k) for k in keys],
        )
        self.conn.commit()

    def history(self, key: str) -> list[Fact]:
        rows = self.conn.execute(
            "SELECT id, key, value, confidence, created_at, updated_at, "
            "referenced_count, last_referenced_at, source_episode_id "
            "FROM facts WHERE key = ? ORDER BY id ASC",
            (key,),
        ).fetchall()
        return [
            Fact(
                id=r["id"],
                key=r["key"],
                value=r["value"],
                confidence=r["confidence"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                referenced_count=r["referenced_count"],
                last_referenced_at=r["last_referenced_at"],
                source_episode_id=r["source_episode_id"],
            )
            for r in rows
        ]
