from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec
from loguru import logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    speaker TEXT NOT NULL,
    text TEXT NOT NULL,
    session_id TEXT,
    importance REAL DEFAULT 0.5,
    referenced_count INTEGER DEFAULT 0,
    last_referenced_at TEXT,
    archived INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_episodes_ts ON episodes(ts);
CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_referenced_at TEXT,
    referenced_count INTEGER DEFAULT 0,
    source_episode_id INTEGER,
    superseded_by INTEGER
);
CREATE INDEX IF NOT EXISTS idx_facts_active ON facts(key) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS screen_obs (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    description TEXT NOT NULL,
    privacy_tag TEXT,
    consumed INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_screen_obs_ts ON screen_obs(ts);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def open_db(path: str | Path, embedding_dim: int) -> sqlite3.Connection:
    """Open (or create) the memory sqlite DB with sqlite-vec loaded."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    # vec0 virtual tables must be created one at a time with concrete dim.
    # distance_metric=cosine requires unit-normalized vectors at insert time.
    try:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS episodes_vec USING vec0("
            f"episode_id INTEGER PRIMARY KEY, "
            f"embedding FLOAT[{embedding_dim}] distance_metric=cosine)"
        )
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS screen_obs_vec USING vec0("
            f"obs_id INTEGER PRIMARY KEY, "
            f"embedding FLOAT[{embedding_dim}] distance_metric=cosine)"
        )
    except sqlite3.OperationalError as e:
        logger.warning("cosine metric not supported; falling back to L2: {}", e)
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS episodes_vec USING vec0("
            f"episode_id INTEGER PRIMARY KEY, embedding FLOAT[{embedding_dim}])"
        )
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS screen_obs_vec USING vec0("
            f"obs_id INTEGER PRIMARY KEY, embedding FLOAT[{embedding_dim}])"
        )
    conn.commit()
    logger.debug("memory db ready at {} (dim={})", path, embedding_dim)
    return conn
