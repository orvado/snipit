"""SQLite persistence for SnipIt."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snippets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    heading    TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
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


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    """Thin wrapper around a sqlite3 connection for snippet CRUD + search."""

    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.first_run = self.count() == 0
        if self.first_run:
            for heading, content in SEED_SNIPPETS:
                self.add(heading, content)

    # ------------------------------------------------------------------ query
    @staticmethod
    def _like(term: str) -> str:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    def search(self, query: str, limit: int = 300):
        """Progressive search: all whitespace-separated terms must match the
        heading or the content (case-insensitive, AND semantics)."""
        terms = [t.strip().lower() for t in query.split() if t.strip()]
        if not terms:
            rows = self.conn.execute(
                "SELECT * FROM snippets ORDER BY lower(heading), id"
            ).fetchall()
        else:
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
                + " ORDER BY lower(heading), id"
            )
            rows = self.conn.execute(sql, params).fetchall()
        return rows[:limit]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM snippets").fetchone()[0]

    def get(self, sid: int):
        return self.conn.execute("SELECT * FROM snippets WHERE id=?", (sid,)).fetchone()

    # ------------------------------------------------------------------ CRUD
    def add(self, heading: str, content: str) -> int:
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO snippets (heading, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (heading, content, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

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
