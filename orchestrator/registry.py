"""SQLite-backed topic registry. Persists thread_id ↔ {name, folder, session_id, perm_mode, model}."""
import sqlite3
import os
from dataclasses import dataclass, field
from typing import Optional

import config

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "registry.db")


@dataclass
class TopicEntry:
    thread_id: int
    name: str
    slug: str
    folder: str
    session_id: Optional[str] = None
    perm_mode: str = "acceptEdits"
    model: str = field(default_factory=lambda: config.DEFAULT_MODEL)
    is_master: bool = False


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                thread_id  INTEGER PRIMARY KEY,
                name       TEXT NOT NULL,
                slug       TEXT NOT NULL,
                folder     TEXT NOT NULL,
                session_id TEXT,
                perm_mode  TEXT NOT NULL DEFAULT 'acceptEdits',
                model      TEXT NOT NULL,
                is_master  INTEGER NOT NULL DEFAULT 0
            )
        """)


def _row_to_entry(row: sqlite3.Row) -> TopicEntry:
    return TopicEntry(
        thread_id=row["thread_id"],
        name=row["name"],
        slug=row["slug"],
        folder=row["folder"],
        session_id=row["session_id"],
        perm_mode=row["perm_mode"],
        model=row["model"],
        is_master=bool(row["is_master"]),
    )


def upsert(entry: TopicEntry) -> None:
    with _conn() as con:
        con.execute("""
            INSERT INTO topics (thread_id, name, slug, folder, session_id, perm_mode, model, is_master)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                name=excluded.name, slug=excluded.slug, folder=excluded.folder,
                session_id=excluded.session_id, perm_mode=excluded.perm_mode,
                model=excluded.model, is_master=excluded.is_master
        """, (entry.thread_id, entry.name, entry.slug, entry.folder,
              entry.session_id, entry.perm_mode, entry.model, int(entry.is_master)))


def update_session(thread_id: int, session_id: str) -> None:
    with _conn() as con:
        con.execute("UPDATE topics SET session_id=? WHERE thread_id=?", (session_id, thread_id))


def update_model(thread_id: int, model: str) -> None:
    with _conn() as con:
        con.execute("UPDATE topics SET model=? WHERE thread_id=?", (model, thread_id))


def get(thread_id: int) -> Optional[TopicEntry]:
    with _conn() as con:
        row = con.execute("SELECT * FROM topics WHERE thread_id=?", (thread_id,)).fetchone()
    return _row_to_entry(row) if row else None


def get_all() -> list[TopicEntry]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM topics ORDER BY is_master DESC, name").fetchall()
    return [_row_to_entry(r) for r in rows]


def get_dev_topics() -> list[TopicEntry]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM topics WHERE is_master=0 ORDER BY name").fetchall()
    return [_row_to_entry(r) for r in rows]


def delete(thread_id: int) -> None:
    with _conn() as con:
        con.execute("DELETE FROM topics WHERE thread_id=?", (thread_id,))
