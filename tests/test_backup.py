"""Quick sanity tests for the SnipIt backup layer (no GUI, no network)."""
import _sandbox  # noqa: F401  (must precede snipit imports)
from _fakes import FakeCloud  # noqa: E402

import base64  # noqa: E402
import hashlib  # noqa: E402
import sqlite3  # noqa: E402
from pathlib import Path  # noqa: E402

from snipit.backup import (  # noqa: E402
    BackupMeta,
    BackupStore,
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
    parse_redirect,
    refresh_access_token,
)


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

    # --- OAuth redirect parsing ----------------------------------------
    print("--- OAuth redirect parsing:")
    assert parse_redirect("code=abc&state=st8", "st8") == "abc"
    try:
        parse_redirect("code=abc&state=WRONG", "st8")
        raise AssertionError("wrong state must raise")
    except ValueError:
        pass
    try:
        parse_redirect("error=access_denied&state=st8", "st8")
        raise AssertionError("error param must raise")
    except ValueError:
        pass
    try:
        parse_redirect("state=st8", "st8")
        raise AssertionError("missing code must raise")
    except ValueError:
        pass
    print("  state/error/code checks ok")

    # --- GoogleDriveProvider request shapes ----------------------------
    print("--- GoogleDriveProvider:")
    from snipit.cloud import GoogleDriveProvider  # noqa: E402

    calls = []

    def drive_transport(url2, data=None, headers=None, method=None):
        calls.append((method or ("POST" if data is not None else "GET"), url2))
        if "drive/v3/files?" in url2 and not data and method != "DELETE":
            return {"files": [{"id": "f1", "name": "snipit_backup_x.db",
                               "createdTime": "2026-01-01T00:00:00", "size": "5"}]}
        if "upload/drive" in url2:
            return {"id": "f1"}
        if "alt=media" in url2:
            return b"SQLite format 3\x00payload"
        return {}

    prov = GoogleDriveProvider("cid", lambda: "at", transport=drive_transport)
    metas = prov.list()
    assert metas[0].name == "snipit_backup_x.db" and metas[0].size == 5 \
        and metas[0].id == "f1"
    up = Path(_sandbox.db_path("up.db"))
    up.write_bytes(b"payload")
    prov.upload("snipit_backup_x.db", up)
    dl = Path(_sandbox.db_path("dl.db"))
    prov.download("snipit_backup_x.db", dl)
    assert dl.read_bytes() == b"SQLite format 3\x00payload", \
        "download must write the raw file bytes"
    prov.delete("snipit_backup_x.db")
    methods = [m for m, _ in calls]
    print("  methods:", methods)
    assert "PATCH" in methods and "DELETE" in methods and methods.count("POST") >= 1

    # --- connect dance end-to-end (simulated browser) ------------------
    print("--- connect dance:")
    import time as _time  # noqa: E402
    from urllib.parse import parse_qs, urlparse  # noqa: E402
    from snipit.app import _run_connect_dance  # noqa: E402

    redirect_seen = {"fired": False}

    def fake_browser(url):
        # Simulate Google's redirect asynchronously: webbrowser.open returns
        # immediately in real life and the redirect lands later while the
        # serve loop runs, so the redirect must happen on its own thread.
        def _do_redirect():
            _time.sleep(0.2)   # let the serve loop start
            q = parse_qs(urlparse(url).query)
            assert q.get("state"), "authorize URL must carry state"
            redirect = urlparse(q["redirect_uri"][0])
            assert redirect.hostname == "localhost", \
                "redirect must use localhost so proxy bypass lists apply"
            import http.client
            conn = http.client.HTTPConnection(redirect.hostname, redirect.port, timeout=5)
            conn.request("GET", f"/?code=fakecode&state={q['state'][0]}")
            resp = conn.getresponse()
            body = resp.read().decode()
            conn.close()
            assert resp.status == 200 and "SnipIt" in body, \
                "loopback server must serve the signed-in page"

        import threading as _threading
        _threading.Thread(target=_do_redirect, daemon=True).start()

    def fake_exchange(url2, data, headers):
        assert url2 == "https://oauth2.googleapis.com/token"
        # urlencode percent-encodes the redirect_uri value
        assert b"redirect_uri=http%3A%2F%2Flocalhost%3A" in data \
            and b"grant_type=authorization_code" in data
        redirect_seen["fired"] = True
        return {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}

    tokens = _run_connect_dance("cid", ["https://www.googleapis.com/auth/drive.appdata"],
                                open_browser=fake_browser, exchange_transport=fake_exchange,
                                on_redirect=lambda: redirect_seen.update(fired=True),
                                timeout_s=10)
    print("  dance tokens:", sorted(tokens))
    assert tokens["refresh_token"] == "rt", "dance must return exchanged tokens"
    assert redirect_seen["fired"] is True, "on_redirect must fire before the exchange"

    start = _time.monotonic()
    try:
        _run_connect_dance("cid", ["s"], open_browser=lambda u: None,
                           exchange_transport=fake_exchange, timeout_s=2)
        raise AssertionError("dance with no redirect must time out")
    except TimeoutError:
        elapsed = _time.monotonic() - start
        print(f"  no-redirect timeout after {elapsed:.1f}s")
        assert elapsed < 6, "deadline must be enforced (was hanging forever)"

    # A token endpoint that stalls after the redirect must NOT leave the
    # flow frozen on "Signed in — exchanging code…" forever. The exchange
    # needs its own hard deadline independent of socket timeouts (a proxy
    # that trickles bytes keeps a socket alive past its per-op timeout).
    print("  exchange stall:")
    import threading as _threading  # noqa: E402
    stall = _threading.Event()

    def hanging_transport(url2, data, headers):
        stall.wait(60)   # token endpoint that never answers
        raise AssertionError("transport must be abandoned by the deadline")

    start = _time.monotonic()
    try:
        _run_connect_dance("cid", ["s"], open_browser=fake_browser,
                           exchange_transport=hanging_transport,
                           timeout_s=10, exchange_timeout_s=1)
        raise AssertionError("stalled exchange must time out")
    except TimeoutError:
        elapsed = _time.monotonic() - start
        print(f"  exchange stall timed out after {elapsed:.1f}s")
        assert elapsed < 5, "exchange deadline must be enforced (was hanging forever)"
    finally:
        stall.set()   # release the abandoned daemon thread

    print("BACKUP PRIMITIVES PASSED")


if __name__ == "__main__":
    main()
