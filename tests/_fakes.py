"""Shared test doubles (import only after _sandbox has set sys.path)."""
from pathlib import Path

from snipit.backup import BackupMeta, CloudProvider


class FakeCloud(CloudProvider):
    """In-memory provider; also records every call for assertions."""

    def __init__(self, files=None, calls=None):
        self.files = {} if files is None else files
        self.calls = [] if calls is None else calls

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
