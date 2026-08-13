"""Verify single-instance IPC and tray icon generation."""
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from snipit.app import _ping_running_instance, _try_bind_ipc  # noqa: E402
from snipit.tray import build_icon_image  # noqa: E402


def main():
    # tray icon renders
    img = build_icon_image()
    print("icon size:", img.size, "mode:", img.mode)
    assert img.size == (64, 64)

    # first instance binds
    srv = _try_bind_ipc()
    assert srv is not None, "first instance should bind the IPC port"

    # second instance fails to bind
    again = _try_bind_ipc()
    assert again is None, "second instance must not bind the same port"
    print("second instance correctly blocked")

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
