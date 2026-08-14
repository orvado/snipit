"""Backup primitives: clean SQLite snapshots via VACUUM INTO + pruning."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .config import MAX_BACKUPS


@dataclass
class BackupMeta:
    name: str
    created_at: str   # provider's timestamp string
    size: int
    id: str = ""      # provider-specific file id (empty for fakes)


class CloudProvider:
    """Minimal cloud backend contract: upload/download/delete/list."""

    def upload(self, name: str, path: Path) -> None:
        raise NotImplementedError

    def download(self, name: str, dest: Path) -> None:
        raise NotImplementedError

    def delete(self, name: str) -> None:
        raise NotImplementedError

    def list(self) -> list[BackupMeta]:
        raise NotImplementedError


def _quote_sql(s: str) -> str:
    return s.replace("'", "''")


def snapshot_db(src_path: Path, dest_dir: Path, prefix: str = "snipit_backup_") -> Path:
    """Write a clean standalone snapshot of the (possibly open) DB.

    VACUUM INTO emits a consistent single-file copy even from a WAL-mode
    database with live connections. The target must not already exist and
    the path is inline SQL (no bound parameters), so quotes are doubled.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Millisecond precision: two backups within the same second must not
    # silently overwrite each other (snapshot names are the storage key).
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    dest = dest_dir / f"{prefix}{stamp}.db"
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


class BackupStore:
    """Snapshot -> upload -> prune orchestration over a CloudProvider."""

    def __init__(self, provider, db_path: Path, local_dir: Path, keep: int = MAX_BACKUPS):
        self.provider = provider
        self.db_path = Path(db_path)
        self.local_dir = Path(local_dir)
        self.keep = keep

    def backup(self) -> str:
        snap = snapshot_db(self.db_path, self.local_dir)
        try:
            self.provider.upload(snap.name, snap)
        except Exception:
            snap.unlink()   # don't leave a local orphan behind a failed upload
            raise
        self._prune_cloud()
        prune_backups(self.local_dir, self.keep)
        return snap.name

    def list_backups(self) -> list[BackupMeta]:
        return sorted(self.provider.list(), key=lambda m: m.created_at, reverse=True)

    def download_verified(self, name: str, dest: Path) -> Path:
        """Download a backup and prove it is a healthy sqlite file."""
        self.provider.download(name, dest)
        conn = sqlite3.connect(str(dest))
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
        finally:
            conn.close()
        if not row or row[0] != "ok":
            raise ValueError(f"downloaded backup failed integrity check: {row}")
        return dest

    def restore(self, live_db, open_factory) -> object:
        """Convenience: prepare (worker-safe) then apply (main-thread only)."""
        tmp = self.prepare_restore(live_db.path)
        return self.apply_restore(live_db, tmp, open_factory)

    def prepare_restore(self, db_path: Path) -> Path:
        """Safety snapshot + download + verify. Worker-thread safe: never
        touches the live connection. Returns the verified temp file."""
        db_path = Path(db_path)
        self._pre_restore_snapshot(db_path)
        tmp = db_path.with_name(f".restore_{uuid4().hex}.db")
        try:
            self.download_verified(self.list_backups()[0].name, tmp)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        return tmp

    def apply_restore(self, live_db, verified_tmp: Path, open_factory) -> object:
        """Close, atomically replace, drop stale WAL, reopen.

        Touches the live connection, so it must run on the UI thread only.
        ``open_factory`` reopens the Database (its __init__ migrates old
        schemas in place, so pre-FTS backups restore cleanly).
        """
        db_path = Path(live_db.path)
        live_db.close()
        os.replace(verified_tmp, db_path)            # atomic, same volume
        for suffix in ("-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        return open_factory(db_path)

    def _pre_restore_snapshot(self, db_path: Path) -> Path:
        """Safety net: snapshot the current local DB before overwriting it."""
        snap = snapshot_db(db_path, self.local_dir, prefix="pre_restore_")
        for old in sorted(self.local_dir.glob("pre_restore_*.db"), reverse=True)[3:]:
            old.unlink()
        return snap

    def _prune_cloud(self) -> None:
        for meta in sorted(self.provider.list(),
                           key=lambda m: m.created_at, reverse=True)[self.keep:]:
            self.provider.delete(meta.name)
