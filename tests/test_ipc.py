"""Verify single-instance detection, IPC signalling and tray icon generation."""
import _sandbox  # noqa: F401  (must precede snipit imports)

from snipit.app import _already_running, _ping_running_instance, _try_bind_ipc  # noqa: E402
from snipit.tray import build_icon_image  # noqa: E402


def main():
    # Single-instance detection hangs off a named mutex, not the port, so an
    # unrelated process squatting on 48731 can no longer impersonate SnipIt.
    assert _already_running() is False, "first call should claim the mutex"
    assert _already_running() is True, "second call should see it is taken"
    print("named-mutex single-instance detection: OK")

    # tray icon renders
    img = build_icon_image()
    print("icon size:", img.size, "mode:", img.mode)
    assert img.size == (64, 64)

    # first instance binds
    srv = _try_bind_ipc()
    assert srv is not None, "first instance should bind the IPC port"

    # a busy port now degrades to "no signalling" instead of refusing to start
    again = _try_bind_ipc()
    assert again is None, "the port cannot be bound twice"
    print("busy port reported (App accepts ipc_socket=None and runs on)")

    # pinging the running instance succeeds
    _ping_running_instance()
    print("ping running instance: OK")

    # the first instance actually receives the ping (accept + show enqueued)
    srv.settimeout(2.0)
    conn, _ = srv.accept()
    conn.close()
    print("first instance received ping: OK")
    srv.close()
    print("IPC TEST PASSED")


if __name__ == "__main__":
    main()
