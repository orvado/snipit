"""SQLite persistence for SnipIt."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snippets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    heading      TEXT NOT NULL DEFAULT '',
    content      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    last_used_at TEXT
);

-- FTS5 mirror for ranked search. Trigram tokenizer (not unicode61): it does
-- real substring matching, which is what code snippets need ("ipconfig /all"
-- must match a query for "ip config"). Triggers keep it in sync; the rowid
-- maps 1:1 to snippets.id.
CREATE VIRTUAL TABLE IF NOT EXISTS snippets_fts USING fts5(
    heading, content, tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS snippets_ai AFTER INSERT ON snippets BEGIN
    INSERT INTO snippets_fts(rowid, heading, content)
    VALUES (new.id, new.heading, new.content);
END;
CREATE TRIGGER IF NOT EXISTS snippets_ad AFTER DELETE ON snippets BEGIN
    DELETE FROM snippets_fts WHERE rowid = old.id;
END;
CREATE TRIGGER IF NOT EXISTS snippets_au AFTER UPDATE ON snippets BEGIN
    DELETE FROM snippets_fts WHERE rowid = old.id;
    INSERT INTO snippets_fts(rowid, heading, content)
    VALUES (new.id, new.heading, new.content);
END;
"""

SEED_SNIPPETS = [
    ("Show IP configuration", "ipconfig /all"),
    ("Flush DNS cache", "ipconfig /flushdns"),
    ("List active TCP connections", "netstat -ano | findstr LISTENING"),
    ("Kill a process by PID", "taskkill /F /PID <pid>"),
    ("PowerShell: process on a port", "Get-NetTCPConnection -LocalPort 8080 | Select-Object OwningProcess"),
    ("Check saved Wi-Fi profiles", "netsh wlan show profiles"),
    ("Open clipboard history", "Win+V"),
    ("ChatGPT: code explainer", "Please explain the following code snippet line by line, assuming I am a beginner:\n\n```\n<code>\n```"),
    ("ChatGPT: rubber duck", "You are my rubber duck. I will describe my plan and reasoning. Ask me sharp questions to help me find flaws in my thinking."),
    ("ChatGPT: TL;DR", "Summarize the following text in 3 bullet points, each at most 12 words:\n\n<text>"),
]


def _now(timespec: str = "seconds") -> str:
    return datetime.now().isoformat(timespec=timespec)


class Database:
    """Thin wrapper around a sqlite3 connection for snippet CRUD + search."""

    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        # Snapshot pre-schema tables so _migrate knows what SCHEMA just created.
        existing = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.conn.executescript(SCHEMA)
        self._migrate(existing)
        self.conn.commit()
        self.first_run = self.count() == 0
        if self.first_run:
            for heading, content in SEED_SNIPPETS:
                self.add(heading, content)

    # ------------------------------------------------------------------ query
    def _migrate(self, existing: set) -> None:
        """Bring older databases up to the current schema (idempotent).

        ``existing`` is the set of tables present *before* SCHEMA ran, so a
        table SCHEMA just created (like ``snippets_fts``) can be detected
        and populated from pre-existing rows.

        Databases created before MRU tracking have no ``last_used_at``
        column. The last edit time is the best available proxy for usage
        recency, so it is backfilled once to give existing snippets a
        sensible initial order.
        """
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(snippets)")}
        needs_mru = "last_used_at" not in cols
        if needs_mru:
            self.conn.execute("ALTER TABLE snippets ADD COLUMN last_used_at TEXT")
        if "snippets_fts" not in existing:
            # Backfill BEFORE any UPDATE on snippets: the AFTER UPDATE
            # trigger re-inserts rows into snippets_fts, so a backfill after
            # it would duplicate rowids and hit the uniqueness constraint.
            self.conn.execute(
                "INSERT INTO snippets_fts(rowid, heading, content) "
                "SELECT id, heading, content FROM snippets"
            )
        if needs_mru:
            self.conn.execute(
                "UPDATE snippets SET last_used_at = updated_at "
                "WHERE last_used_at IS NULL"
            )

    @staticmethod
    def _like(term: str) -> str:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    # NULL (never used) sorts last under DESC, so used snippets come first.
    _MRU_ORDER = "ORDER BY last_used_at DESC, updated_at DESC, id DESC"

    def search(self, query: str, limit: int = 300):
        """Progressive search: all whitespace-separated terms must match the
        heading or the content (case-insensitive, AND semantics).

        Results are ordered most-recently-used first; never-used snippets
        sort below them by last edit, then newest id.
        """
        terms = [t.strip().lower() for t in query.split() if t.strip()]
        if not terms:
            return self.conn.execute(
                f"SELECT * FROM snippets {self._MRU_ORDER} LIMIT ?", (limit,)
            ).fetchall()

        clauses, params = [], []
        for t in terms:
            like = self._like(t)
            clauses.append(
                "(lower(heading) LIKE ? ESCAPE '\\' OR lower(content) LIKE ? ESCAPE '\\')"
            )
            params += [like, like]
        sql = (
            "SELECT * FROM snippets WHERE "
            + " AND ".join(clauses)
            + f" {self._MRU_ORDER} LIMIT ?"
        )
        return self.conn.execute(sql, params + [limit]).fetchall()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM snippets").fetchone()[0]

    def get(self, sid: int):
        return self.conn.execute("SELECT * FROM snippets WHERE id=?", (sid,)).fetchone()

    # ------------------------------------------------------------------ CRUD
    def add(self, heading: str, content: str) -> int:
        now = _now()
        # A freshly added snippet counts as "just used" so it surfaces at the
        # top of the MRU list until something else is copied.
        cur = self.conn.execute(
            "INSERT INTO snippets (heading, content, created_at, updated_at, "
            "last_used_at) VALUES (?, ?, ?, ?, ?)",
            (heading, content, now, now, _now("milliseconds")),
        )
        self.conn.commit()
        return cur.lastrowid

    def mark_used(self, sid: int) -> None:
        """Record that a snippet was used (copied or viewed) — drives the
        MRU ordering of search results. Millisecond precision so rapid
        consecutive uses don't tie."""
        self.conn.execute(
            "UPDATE snippets SET last_used_at=? WHERE id=?",
            (_now("milliseconds"), sid),
        )
        self.conn.commit()

    def update(self, sid: int, heading: str, content: str) -> None:
        self.conn.execute(
            "UPDATE snippets SET heading=?, content=?, updated_at=? WHERE id=?",
            (heading, content, _now(), sid),
        )
        self.conn.commit()

    def delete(self, sid: int) -> None:
        self.conn.execute("DELETE FROM snippets WHERE id=?", (sid,))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
