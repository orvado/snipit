"""Quick sanity tests for the SnipIt data layer (no GUI needed)."""
import _sandbox  # noqa: F401  (must precede snipit imports)

import sqlite3  # noqa: E402
import time  # noqa: E402

from snipit.db import Database  # noqa: E402


def main():
    path = _sandbox.db_path()
    db = Database(path)
    print("first_run:", db.first_run)
    print("count:", db.count())

    print("--- empty query (first 3):")
    for r in db.search("")[:3]:
        print("  ", r["id"], "|", r["heading"], "|", r["content"][:40])

    print("--- search 'ip config' (multi-term AND):", [r["heading"] for r in db.search("ip config")])
    print("--- search 'chatgpt rubber':", [r["heading"] for r in db.search("chatgpt rubber")])
    print("--- search 'zzzznomatch':", len(db.search("zzzznomatch")))

    sid = db.add("test snippet", "unique needle 42")
    print("--- added id", sid, "| search 'needle 42':",
          [r["heading"] for r in db.search("needle 42")])
    db.update(sid, "renamed", "unique needle 43")
    row = db.get(sid)
    print("--- updated:", row["heading"], "|", row["content"])

    sid2 = db.add("percent test", "50% done")
    print("--- literal % search:", [r["heading"] for r in db.search("50%")])
    db.delete(sid2)
    db.delete(sid)
    print("--- after delete, count:", db.count())

    # --- MRU ordering ------------------------------------------------
    print("--- MRU ordering:")
    a = db.add("mru alpha", "needle mru")
    b = db.add("mru beta", "needle mru")
    rows = db.search("mru")
    print("  initial:", [(r["id"], r["heading"]) for r in rows if r["id"] in (a, b)])
    assert rows[0]["id"] == b, "before any use, newest addition sorts first"
    time.sleep(0.01)  # last_used_at has ms precision; stay out of a tie
    db.mark_used(a)
    rows = db.search("mru")
    assert rows[0]["id"] == a, "a used snippet sorts above unused ones"
    time.sleep(0.01)  # last_used_at has ms precision; stay out of a tie
    db.mark_used(b)
    rows = db.search("mru")
    assert rows[0]["id"] == b, "most recently used sorts first"
    time.sleep(0.01)
    db.mark_used(a)
    rows = db.search("")
    assert rows[0]["id"] == a, "empty query also orders MRU first"
    rows = db.search("mru")
    assert rows[0]["id"] == a, "filtered search orders MRU first too"
    db.delete(a)
    db.delete(b)

    # --- migration: old schema gains last_used_at ---------------------
    print("--- migration from pre-MRU schema:")
    legacy = _sandbox.db_path("legacy.db")
    conn = sqlite3.connect(legacy)
    conn.executescript(
        "CREATE TABLE snippets (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "heading TEXT NOT NULL DEFAULT '', content TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
        "INSERT INTO snippets (heading, content, created_at, updated_at) "
        "VALUES ('legacy', 'old data', '2024-01-01T00:00:00', '2024-06-01T00:00:00');"
    )
    conn.commit()
    conn.close()
    db3 = Database(legacy)
    cols = {r["name"] for r in db3.conn.execute("PRAGMA table_info(snippets)")}
    assert "last_used_at" in cols, "migration must add the last_used_at column"
    assert db3.get(1)["last_used_at"] == "2024-06-01T00:00:00", \
        "migration must backfill last_used_at from updated_at"
    assert db3.count() == 1, "migration must not seed an existing database"
    db3.close()
    print("--- migration ok, column:", sorted(cols))

    # --- FTS5: virtual table exists and stays in sync -----------------
    print("--- FTS5 sync:")
    fts_count = db.conn.execute("SELECT count(*) FROM snippets_fts").fetchone()[0]
    assert fts_count == db.count(), "FTS table must mirror snippets"
    sid = db.add("fts sync", "unique fts token abc")
    assert db.conn.execute(
        "SELECT content FROM snippets_fts WHERE rowid=?", (sid,)
    ).fetchone()[0] == "unique fts token abc"
    db.update(sid, "fts sync", "changed fts token xyz")
    assert db.conn.execute(
        "SELECT content FROM snippets_fts WHERE rowid=?", (sid,)
    ).fetchone()[0] == "changed fts token xyz"
    db.delete(sid)
    assert db.conn.execute(
        "SELECT count(*) FROM snippets_fts WHERE rowid=?", (sid,)
    ).fetchone()[0] == 0

    # --- FTS5: legacy database is backfilled --------------------------
    print("--- FTS5 migration backfill:")
    legacy2 = _sandbox.db_path("legacy2.db")
    conn = sqlite3.connect(legacy2)
    conn.executescript(
        "CREATE TABLE snippets (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "heading TEXT NOT NULL DEFAULT '', content TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_used_at TEXT);"
        "INSERT INTO snippets (heading, content, created_at, updated_at) "
        "VALUES ('legacy', 'old data xyz', '2024-01-01T00:00:00', '2024-06-01T00:00:00');"
    )
    conn.commit()
    conn.close()
    db4 = Database(legacy2)
    n = db4.conn.execute("SELECT count(*) FROM snippets_fts").fetchone()[0]
    assert n == db4.count(), "FTS must be backfilled on migration"
    assert db4.conn.execute(
        "SELECT content FROM snippets_fts WHERE rowid=1"
    ).fetchone()[0] == "old data xyz"
    db4.close()

    # persistence: reopen
    db.close()
    db2 = Database(path)
    print("--- reopened first_run (should be False):", db2.first_run)
    db2.close()
    print("DB TESTS PASSED")


if __name__ == "__main__":
    main()
