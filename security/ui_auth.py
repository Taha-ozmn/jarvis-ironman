"""Local pairing-token authentication for the LAN HUD and mobile client."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Any


PAIRING_QUERY_KEY = "pairing"
PAIRING_HEADER = "X-Jarvis-Pairing-Token"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PairingTokenAuth:
    """Issue one stable pairing token, persisted across restarts.

    The token is stored in a sibling secret file with 0600 permissions so the
    phone link and its QR code stay identical across launchd restarts. If the
    secret store is unreadable/unwritable, a fresh in-memory token is minted so
    pairing keeps working (at the cost of QR stability for that boot).
    """

    _MIN_TOKEN_LEN = 24

    def __init__(self, state_path: str | Path) -> None:
        self.state_path = Path(state_path).expanduser().resolve()
        self.secret_path = self.state_path.with_name(
            self.state_path.stem + "_token.secret"
        )
        self.token = self._load_or_create_token()
        self.token_hash = _hash_token(self.token)
        self._write_metadata()

    def _load_or_create_token(self) -> str:
        """Reuse a persisted token when present; otherwise mint and store one."""
        existing = self._read_persisted_token()
        if existing:
            return existing
        token = secrets.token_urlsafe(32)
        self._persist_token(token)
        return token

    def _read_persisted_token(self) -> str:
        try:
            raw = self.secret_path.read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return ""
        # Guard against truncated / tampered files.
        return raw if len(raw) >= self._MIN_TOKEN_LEN else ""

    def _persist_token(self, token: str) -> None:
        try:
            self.secret_path.parent.mkdir(parents=True, exist_ok=True)
            self.secret_path.write_text(token + "\n", encoding="utf-8")
            self.secret_path.chmod(0o600)
        except OSError:
            # Persisting is best-effort; the in-memory token still authorizes.
            pass

    def _write_metadata(self) -> None:
        """Record only non-secret pairing metadata for diagnostics."""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                '{"active": true, "token_storage": "persistent-file"}\n',
                encoding="utf-8",
            )
            self.state_path.chmod(0o600)
        except OSError:
            # Pairing must continue to work if diagnostics storage is read-only.
            pass

    def verify(self, token: str | None) -> bool:
        candidate = _hash_token(str(token or ""))
        return hmac.compare_digest(candidate, self.token_hash)

    def token_from_request(self, request: Any) -> str:
        header = str(request.headers.get(PAIRING_HEADER, "")).strip()
        if header:
            return header
        authorization = str(request.headers.get("Authorization", "")).strip()
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        query = getattr(request, "query", {})
        return str(query.get(PAIRING_QUERY_KEY, "")).strip()

    def authorized(self, request: Any) -> bool:
        return self.verify(self.token_from_request(request))

    def is_local_request(self, request: Any) -> bool:
        remote = str(getattr(request, "remote", "") or "")
        return remote in {"127.0.0.1", "::1", "localhost"}

    def public_payload(self) -> dict[str, Any]:
        return {
            "pairing_query_key": PAIRING_QUERY_KEY,
            "pairing_header": PAIRING_HEADER,
            "token_storage": "persistent-file",
        }
