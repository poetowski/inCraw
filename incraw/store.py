"""SQLite storage for checks. One row per person per request."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import date
from pathlib import Path

from .inputs import Request

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch        TEXT NOT NULL,
    raw          TEXT NOT NULL,
    kind         TEXT NOT NULL,          -- url | name
    query_name   TEXT DEFAULT '',
    query_company TEXT DEFAULT '',
    slug         TEXT DEFAULT '',
    status       TEXT NOT NULL,          -- queued, running, open, likely, not_detected,
                                         -- ambiguous, not_found, unavailable, blocked, error
    profile_name TEXT DEFAULT '',
    headline     TEXT DEFAULT '',
    roles        TEXT DEFAULT '',
    signals      TEXT DEFAULT '[]',
    candidates   TEXT DEFAULT '[]',
    note         TEXT DEFAULT '',
    from_cache   INTEGER DEFAULT 0,
    created_at   REAL NOT NULL,
    checked_at   REAL
);
CREATE INDEX IF NOT EXISTS items_slug ON items(slug);
CREATE TABLE IF NOT EXISTS page_loads (day TEXT PRIMARY KEY, n INTEGER NOT NULL);
"""

FINISHED = ("open", "likely", "not_detected", "unavailable")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            # a crash mid-check leaves rows "running"; put them back in line
            self._db.execute("UPDATE items SET status='queued' WHERE status='running'")
            self._db.commit()

    def _exec(self, sql: str, args=()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur

    def add(self, batch: str, req: Request) -> int:
        cur = self._exec(
            "INSERT INTO items(batch, raw, kind, query_name, query_company, slug, status, created_at)"
            " VALUES (?,?,?,?,?,?, 'queued', ?)",
            (batch, req.raw, req.kind, req.name, req.company, req.slug, time.time()),
        )
        return cur.lastrowid

    def get(self, item_id: int) -> dict | None:
        row = self._exec("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return _row(row) if row else None

    def update(self, item_id: int, **fields) -> None:
        for k in ("signals", "candidates"):
            if k in fields and not isinstance(fields[k], str):
                fields[k] = json.dumps(fields[k], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE items SET {cols} WHERE id=?", (*fields.values(), item_id))

    def queued_ids(self) -> list[int]:
        return [r[0] for r in self._exec("SELECT id FROM items WHERE status='queued' ORDER BY id")]

    def cached(self, slug: str, max_age_days: float) -> dict | None:
        row = self._exec(
            f"SELECT * FROM items WHERE slug=? AND status IN {FINISHED} AND from_cache=0"
            " AND checked_at > ? ORDER BY checked_at DESC LIMIT 1",
            (slug, time.time() - max_age_days * 86400),
        ).fetchone()
        return _row(row) if row else None

    def items(self, batch: str | None = None, limit: int = 500) -> list[dict]:
        if batch:
            rows = self._exec("SELECT * FROM items WHERE batch=? ORDER BY id", (batch,))
        else:
            rows = self._exec("SELECT * FROM items ORDER BY id DESC LIMIT ?", (limit,))
        return [_row(r) for r in rows]

    def batches(self, limit: int = 30) -> list[dict]:
        rows = self._exec(
            "SELECT batch, COUNT(*) n, MIN(created_at) created_at,"
            " SUM(status='open') open, SUM(status IN ('queued','running')) pending"
            " FROM items GROUP BY batch ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    def delete_batch(self, batch: str) -> None:
        self._exec("DELETE FROM items WHERE batch=? AND status NOT IN ('running')", (batch,))

    # daily page-load budget, to keep the account under LinkedIn's radar
    def loads_today(self) -> int:
        row = self._exec("SELECT n FROM page_loads WHERE day=?", (date.today().isoformat(),)).fetchone()
        return row[0] if row else 0

    def count_load(self) -> None:
        self._exec(
            "INSERT INTO page_loads(day, n) VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET n = n + 1",
            (date.today().isoformat(),),
        )


def _row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["signals"] = json.loads(d.get("signals") or "[]")
    d["candidates"] = json.loads(d.get("candidates") or "[]")
    d["url"] = f"https://www.linkedin.com/in/{d['slug']}/" if d.get("slug") else ""
    return d
