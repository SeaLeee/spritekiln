"""SQLite persistence (projects, assets, jobs, agent messages)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterable

from .config import DATA_DIR

DB_PATH = DATA_DIR / "spritekiln.db"
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT DEFAULT 'general',
  description TEXT DEFAULT '', style TEXT DEFAULT '{}', viewport TEXT DEFAULT '{}',
  created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT,
  path TEXT, width INTEGER, height INTEGER, meta TEXT DEFAULT '{}', parents TEXT DEFAULT '[]',
  job_id TEXT, capability TEXT, x REAL DEFAULT 0, y REAL DEFAULT 0, favorite INTEGER DEFAULT 0,
  tags TEXT DEFAULT '[]', role TEXT DEFAULT 'output', created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_assets_project ON assets(project_id);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, project_id TEXT, capability TEXT NOT NULL, params TEXT DEFAULT '{}',
  status TEXT NOT NULL, progress REAL DEFAULT 0, message TEXT DEFAULT '', lane TEXT DEFAULT 'cpu',
  providers TEXT DEFAULT '{}', result TEXT DEFAULT '[]', error TEXT, cost_usd REAL DEFAULT 0,
  source TEXT DEFAULT 'web', created_at REAL, started_at REAL, finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, project_id TEXT, role TEXT NOT NULL,
  content TEXT, data TEXT DEFAULT '{}', created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);
"""

JSON_FIELDS = {"style", "viewport", "meta", "parents", "tags", "params", "providers", "result", "data"}


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(SCHEMA)
        return _conn


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now() -> float:
    return time.time()


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for k in JSON_FIELDS & out.keys():
        try:
            out[k] = json.loads(out[k]) if out[k] else ({} if k not in {"parents", "tags", "result"} else [])
        except (TypeError, json.JSONDecodeError):
            pass
    if "favorite" in out:
        out["favorite"] = bool(out["favorite"])
    return out


def _encode(values: dict[str, Any]) -> dict[str, Any]:
    return {k: (json.dumps(v, ensure_ascii=False) if k in JSON_FIELDS and not isinstance(v, str) else v) for k, v in values.items()}


def insert(table: str, values: dict[str, Any]) -> dict[str, Any]:
    vals = _encode(values)
    cols = ",".join(vals)
    qs = ",".join("?" for _ in vals)
    with _lock:
        conn().execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", list(vals.values()))
    return get(table, values["id"])  # type: ignore[return-value]


def update(table: str, id_: str, values: dict[str, Any]) -> dict[str, Any] | None:
    if values:
        vals = _encode(values)
        sets = ",".join(f"{k}=?" for k in vals)
        with _lock:
            conn().execute(f"UPDATE {table} SET {sets} WHERE id=?", [*vals.values(), id_])
    return get(table, id_)


def get(table: str, id_: str) -> dict[str, Any] | None:
    with _lock:
        row = conn().execute(f"SELECT * FROM {table} WHERE id=?", (id_,)).fetchone()
    return _decode(row)


def delete(table: str, id_: str) -> None:
    with _lock:
        conn().execute(f"DELETE FROM {table} WHERE id=?", (id_,))


def query(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with _lock:
        rows = conn().execute(sql, list(params)).fetchall()
    return [_decode(r) for r in rows]  # type: ignore[misc]


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    with _lock:
        conn().execute(sql, list(params))
