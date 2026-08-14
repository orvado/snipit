"""Quick sanity tests for the SnipIt backup layer (no GUI, no network)."""
import _sandbox  # noqa: F401  (must precede snipit imports)

import sqlite3  # noqa: E402
from pathlib import Path  # noqa: E402

from snipit.backup import prune_backups, snapshot_db  # noqa: E402
from snipit.db import Database  # noqa: E402


def main():
    db = Database(_sandbox.db_path())
    db.add("snap", "unique probe 123")
    out = snapshot_db(Path(db.path), Path(_sandbox.db_path("backups")))
    print("snapshot:", out.name)
    assert out.exists() and out.name.startswith("snipit_backup_")
    c = sqlite3.connect(str(out))
    assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert c.execute("SELECT count(*) FROM snippets").fetchone()[0] == db.count()
    c.close()
    db.add("snap2", "more data")
    snapshot_db(Path(db.path), out.parent)          # second snapshot, keep 1
    for _ in range(3):
        snapshot_db(Path(db.path), out.parent)
    prune_backups(out.parent, keep=1)
    left = sorted(out.parent.glob("snipit_backup_*.db"))
    assert len(left) == 1, "prune must keep only the newest snapshot"
    db.close()
    print("BACKUP PRIMITIVES PASSED")


if __name__ == "__main__":
    main()
