"""Google Drive appDataFolder provider (backup target: hidden per-app space)."""
from __future__ import annotations

import json
import os
import urllib.error
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
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(
                f"Drive API {exc.code}: {detail or exc.reason}") from exc
        return json.loads(raw.decode()) if raw else {}

    def _request_bytes(self, url: str) -> bytes:
        headers = {"Authorization": f"Bearer {self._token()}"}
        if self._transport is not None:
            return self._transport(url, None, headers, method="GET")
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(
                f"Drive API {exc.code}: {detail or exc.reason}") from exc

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
        # Multipart upload with parents pinned to appDataFolder: creates the
        # file directly inside the hidden per-app space in one request. The
        # naive media-upload-then-PATCH flow creates the file in the user's
        # My Drive root first, which a drive.appdata-scoped app is forbidden
        # to touch (HTTP 403).
        boundary = f"snipit{os.urandom(8).hex()}"
        meta = json.dumps({"name": name, "parents": [APP_DATA_FOLDER]}).encode()
        payload = path.read_bytes()
        body = (f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                ).encode() + meta + b"\r\n" + (
                f"--{boundary}\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n"
                ).encode() + payload + b"\r\n" + f"--{boundary}--\r\n".encode()
        self._request_json(
            "POST", f"{DRIVE_UPLOAD}?uploadType=multipart",
            body, f"multipart/related; boundary={boundary}")

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
