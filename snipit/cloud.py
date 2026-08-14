"""Google Drive appDataFolder provider (backup target: hidden per-app space)."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

from .backup import BackupMeta

DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
APP_DATA_FOLDER = "appDataFolder"


class GoogleDriveProvider:
    """Drive appDataFolder backend. ``transport`` is injectable for tests.

    ``access_token_getter`` is called per request to supply a Bearer token,
    so refresh logic can be layered on without touching this class. A
    transport, when given, is called as ``transport(url, body, headers,
    method=...)`` and returns a dict for JSON endpoints or bytes for
    ``alt=media`` downloads.
    """

    def __init__(self, client_id: str, access_token_getter, transport=None):
        self._client_id = client_id
        self._token = access_token_getter
        self._transport = transport

    def _request_json(self, method: str, url: str, body: bytes | None = None,
                      content_type: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._token()}"}
        if content_type:
            headers["Content-Type"] = content_type
        if self._transport is not None:
            return self._transport(url, body, headers, method=method)
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
        return json.loads(raw.decode()) if raw else {}

    def _request_bytes(self, url: str) -> bytes:
        headers = {"Authorization": f"Bearer {self._token()}"}
        if self._transport is not None:
            return self._transport(url, None, headers, method="GET")
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    def list(self) -> list[BackupMeta]:
        q = urllib.parse.urlencode({
            "spaces": APP_DATA_FOLDER,
            "pageSize": 100,
            "orderBy": "createdTime desc",
            "fields": "files(id,name,createdTime,size)",
        })
        data = self._request_json("GET", f"{DRIVE_API}/files?{q}")
        return [BackupMeta(f["name"], f.get("createdTime", ""),
                           int(f.get("size", 0)), id=f.get("id", ""))
                for f in data.get("files", [])]

    def upload(self, name: str, path: Path) -> None:
        file_id = self._request_json(
            "POST", f"{DRIVE_UPLOAD}?uploadType=media",
            path.read_bytes(), "application/octet-stream")["id"]
        # appDataFolder is a hidden parent; move the uploaded file into it
        # and set its display name.
        self._request_json(
            "PATCH",
            f"{DRIVE_API}/files/{file_id}?addParents={APP_DATA_FOLDER}&fields=id",
            json.dumps({"name": name}).encode(), "application/json")

    def download(self, name: str, dest: Path) -> None:
        meta = self._find(name)
        data = self._request_bytes(f"{DRIVE_API}/files/{meta.id}?alt=media")
        dest.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())

    def delete(self, name: str) -> None:
        meta = self._find(name)
        self._request_json("DELETE", f"{DRIVE_API}/files/{meta.id}")

    def _find(self, name: str) -> BackupMeta:
        for meta in self.list():
            if meta.name == name:
                return meta
        raise FileNotFoundError(f"backup not found on cloud: {name}")
