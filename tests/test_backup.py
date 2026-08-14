"""Quick sanity tests for the SnipIt backup layer (no GUI, no network)."""
import _sandbox  # noqa: F401  (must precede snipit imports)

import base64  # noqa: E402
import hashlib  # noqa: E402
import sqlite3  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

from snipit.backup import (  # noqa: E402
    BackupMeta,
    BackupStore,
    CloudProvider,
    prune_backups,
    snapshot_db,
)
from snipit.db import Database  # noqa: E402
from snipit.oauth import (  # noqa: E402
    TokenStore,
    build_authorize_url,
    exchange_code,
    make_code_challenge,
    make_code_verifier,
    refresh_access_token,
)


@dataclass
class FakeCloud(CloudProvider):
    """In-memory provider; also records every call for assertions."""

    files: dict = None
    calls: list = None

    def __post_init__(self):
        self.files = {} if self.files is None else self.files
        self.calls = [] if self.calls is None else self.calls

    def upload(self, name: str, path: Path) -> None:
        self.calls.append(("upload", name))
        self.files[name] = path.read_bytes()

    def download(self, name: str, dest: Path) -> None:
        self.calls.append(("download", name))
        dest.write_bytes(self.files[name])

    def delete(self, name: str) -> None:
        self.calls.append(("delete", name))
        self.files.pop(name, None)

    def list(self) -> list[BackupMeta]:
        # created_at mirrors the name so ordering is deterministic (names
        # are timestamps, newest sorts last in ascending order).
        return [BackupMeta(n, n, len(b), id=n)
                for n, b in sorted(self.files.items())]


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

    # --- BackupStore: snapshot -> upload -> prune ----------------------
    print("--- BackupStore.backup:")
    cloud = FakeCloud()
    store = BackupStore(cloud, Path(db.path), Path(_sandbox.db_path("backups")), keep=3)
    name = store.backup()
    print("  uploaded:", name)
    assert name in cloud.files, "backup must upload a snapshot"
    assert cloud.files[name][:16] == b"SQLite format 3\x00", \
        "uploaded file must be a sqlite db"
    for _ in range(4):
        store.backup()
    assert len(cloud.files) == 3, "cloud must be pruned to keep"
    assert len(list(Path(_sandbox.db_path("backups")).glob("snipit_backup_*.db"))) == 3
    print("  cloud files kept:", sorted(cloud.files))

    # --- BackupStore.restore: verified round-trip ----------------------
    print("--- BackupStore.restore:")
    db.add("restore marker", "restore needle unique")
    before = db.count()
    store.backup()                          # snapshot BEFORE further edits
    db.add("post-backup", "should be gone after restore")
    db.update(db.search("restore needle unique")[0]["id"],
              "renamed", "restore needle unique")
    target = Path(db.path)
    restored = store.restore(db, open_factory=lambda p: Database(p))
    db = restored    # the old handle was closed by restore; keep this one
    print("  before:", before, "| restored count:", db.count())
    assert db.count() == before, "restored db must match the backup snapshot"
    assert not db.search("post-backup"), "post-backup edits must not survive restore"
    row = db.search("restore needle unique")[0]
    assert row["heading"] == "restore marker", "heading must be back to the snapshot value"
    # A stale -wal left next to the replaced db would replay pre-restore
    # rows on the next open; the post-backup assertion above catches that.
    # (While a WAL-mode Database is OPEN, its own fresh -wal/-shm exist —
    # they must be gone after a clean close.)
    db.close()
    assert not target.with_name(target.name + "-wal").exists(), \
        "no stale WAL may survive a clean close"

    # --- OAuth PKCE helpers + token store ------------------------------
    print("--- OAuth PKCE:")
    verifier = make_code_verifier()
    assert 43 <= len(verifier) <= 128
    ch = make_code_challenge(verifier)
    assert ch == base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = build_authorize_url(
        "cid", "http://127.0.0.1:8123/", "st8", verifier,
        ["https://www.googleapis.com/auth/drive.appdata"])
    assert "code_challenge=" + ch in url and "state=st8" in url \
        and "access_type=offline" in url and "client_id=cid" in url
    calls = []

    def fake_post(url2, data, headers):
        calls.append((url2, data, headers))
        return {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}

    tok = exchange_code(fake_post, "thecode", verifier, "http://127.0.0.1:8123/", "cid")
    assert tok["refresh_token"] == "rt"
    assert b"grant_type=authorization_code" in calls[0][1]
    assert b"code_verifier=" + verifier.encode() in calls[0][1]
    tok2 = refresh_access_token(fake_post, "rt", "cid")
    assert tok2["access_token"] == "at"
    assert b"grant_type=refresh_token" in calls[-1][1]
    ts = TokenStore(_sandbox.db_path("token.json"))
    ts.save({"refresh_token": "rt", "access_token": "at", "expires_at": 0})
    assert ts.load()["refresh_token"] == "rt"
    assert TokenStore(_sandbox.db_path("missing.json")).load() == {}
    print("  PKCE url:", url[:80], "…")

    print("BACKUP PRIMITIVES PASSED")


if __name__ == "__main__":
    main()
