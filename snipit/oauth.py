"""OAuth2 Authorization Code + PKCE for public clients (stdlib only)."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.parse
import urllib.request
from pathlib import Path

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

_VERIFIER_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def make_code_verifier(n: int = 64) -> str:
    return "".join(secrets.choice(_VERIFIER_ALPHABET) for _ in range(n))


def make_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def build_authorize_url(client_id: str, redirect_uri: str, state: str,
                        verifier: str, scopes: list[str]) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": make_code_challenge(verifier),
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


def _post_form(transport, url: str, data: dict) -> dict:
    """POST urlencoded data; ``transport`` is injectable for tests.

    A transport is called as ``transport(url, body_bytes, headers)`` and
    must return the parsed JSON dict. When None, urllib is used directly.
    """
    body = urllib.parse.urlencode(data).encode()
    if transport is None:
        req = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    return transport(url, body, {})


def exchange_code(transport, code: str, verifier: str, redirect_uri: str,
                  client_id: str) -> dict:
    return _post_form(transport, GOOGLE_TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    })


def refresh_access_token(transport, refresh_token: str, client_id: str) -> dict:
    return _post_form(transport, GOOGLE_TOKEN_URL, {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    })


class TokenStore:
    """Persists OAuth tokens as JSON in the app data dir."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, tokens: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(tokens), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
