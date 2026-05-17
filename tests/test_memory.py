"""Unit tests that don't need a live LLM/embedding API."""

from __future__ import annotations

from pathlib import Path

from core.memory import FactStore, WorkingMemory, open_db


def test_fact_store_create(tmp_path: Path):
    conn = open_db(tmp_path / "m.sqlite", embedding_dim=4)
    fs = FactStore(conn)
    f = fs.upsert("user.profile.name", "小李", confidence=0.7)
    assert f.value == "小李"
    assert fs.get("user.profile.name").value == "小李"
    conn.close()


def test_fact_store_supersession(tmp_path: Path):
    conn = open_db(tmp_path / "m.sqlite", embedding_dim=4)
    fs = FactStore(conn)

    fs.upsert("user.profile.name", "小李", confidence=0.7)
    bumped = fs.upsert("user.profile.name", "小李", confidence=0.7)
    assert bumped.confidence > 0.7, "same value should bump confidence"

    superseded = fs.upsert("user.profile.name", "李雷", confidence=0.9)
    assert superseded.value == "李雷"
    active = [f for f in fs.all_active() if f.key == "user.profile.name"]
    assert len(active) == 1, "exactly one active fact per key"
    assert active[0].value == "李雷"

    history = fs.history("user.profile.name")
    assert len(history) == 2, "supersession preserves history"
    conn.close()


def test_fact_store_history_ordering(tmp_path: Path):
    conn = open_db(tmp_path / "m.sqlite", embedding_dim=4)
    fs = FactStore(conn)
    fs.upsert("user.work.role", "学生")
    fs.upsert("user.work.role", "工程师")
    fs.upsert("user.work.role", "创业者")
    h = fs.history("user.work.role")
    assert [f.value for f in h] == ["学生", "工程师", "创业者"]
    assert fs.get("user.work.role").value == "创业者"
    conn.close()


def test_working_memory_window():
    w = WorkingMemory(max_turns=3)
    w.append("user", "a")
    w.append("assistant", "b")
    w.append("user", "c")
    w.append("assistant", "d")
    turns = w.turns()
    assert len(turns) == 3
    assert turns[0].text == "b"
    assert turns[-1].text == "d"


def test_db_idempotent(tmp_path: Path):
    p = tmp_path / "m.sqlite"
    c1 = open_db(p, embedding_dim=4)
    c1.close()
    c2 = open_db(p, embedding_dim=4)
    # tables already exist; this should not throw
    c2.execute("INSERT INTO facts(key, value, confidence, created_at, updated_at) VALUES('k','v',1.0,'t','t')")
    c2.commit()
    c2.close()
