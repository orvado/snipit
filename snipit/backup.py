"""Backup primitives: clean SQLite snapshots via VACUUM INTO + pruning."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .config import MAX_BACKUPS


def _quote_sql(s: str) -> str:
    return s.replace("'", "''")


def snapshot_db(src_path: Path, dest_dir: Path, prefix: str = "snipit_backup_") -> Path:
    """Write a clean standalone snapshot of the (possibly open) DB.

    VACUUM INTO emits a consistent single-file copy even from a WAL-mode
    database with live connections. The target must not already exist and
    the path is inline SQL (no bound parameters), so quotes are doubled.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{prefix}{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    if dest.exists():
        dest.unlink()
    conn = sqlite3.connect(str(src_path))
    try:
        conn.execute(f"VACUUM INTO '{_quote_sql(str(dest))}'")
    finally:
        conn.close()
    return dest


def prune_backups(dir_path: Path, keep: int = MAX_BACKUPS) -> list[Path]:
    """Delete oldest snipit_backup_*.db files beyond ``keep``."""
    files = sorted(dir_path.glob("snipit_backup_*.db"), reverse=True)
    for old in files[keep:]:
        old.unlink()
    return files[:keep]
