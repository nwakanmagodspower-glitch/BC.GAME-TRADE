"""DeTradeTokenService — parses, validates, persists, and hot-reloads DeTrade JWTs.

This service is the single authoritative path for updating the DeTrade WebSocket
token at runtime.  It writes the token to the `runtime_settings` database table
(key: 'detrade_ws_token') so it survives Render restarts, then instructs the
live DeTradeObserver to reconnect immediately with the new credential.

Design rules:
  - Never stores or logs the full token in human-readable Telegram replies.
  - Smart extraction: accepts the raw JWT *or* any pasted text (DevTools cURL,
    full WebSocket URL, HTTP header block) and finds the JWT automatically.
  - Fails closed: rejects expired, malformed, or placeholder tokens before
    they reach the observer.
  - Full audit trail via AuditLog for every token update attempt.
"""
from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.integrations.detrade_token_provider import (
    PLACEHOLDER_TOKENS,
    detrade_token_is_expired,
)
from app.models.entities import AuditLog, RuntimeSetting

# Key used in runtime_settings table
DETRADE_TOKEN_KEY = 'detrade_ws_token'

# JWT pattern: three base64url segments separated by dots
_JWT_RE = re.compile(r'eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+')


@dataclass(frozen=True)
class TokenUpdateResult:
    ok: bool
    error: str | None
    # These are safe to surface to the owner, never the raw token:
    expires_at: datetime | None
    remaining_hours: float | None
    remaining_minutes: int | None


def _extract_jwt(raw_text: str) -> str | None:
    """Extract the first JWT from any pasted text (URL, cURL, header block, etc.)."""
    match = _JWT_RE.search(raw_text)
    return match.group(0) if match else None


def _decode_jwt_claims(token: str) -> dict | None:
    parts = token.strip().split('.')
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + ('=' * (-len(parts[1]) % 4))
        return json.loads(base64.urlsafe_b64decode(padded).decode('utf-8'))
    except Exception:
        return None


def _token_expiry(token: str) -> datetime | None:
    claims = _decode_jwt_claims(token)
    if claims is None:
        return None
    try:
        return datetime.fromtimestamp(float(claims['exp']), tz=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None


def _remaining(expiry: datetime) -> tuple[float, int]:
    """Return (remaining_hours_float, remaining_whole_minutes_int)."""
    delta_seconds = max(0.0, (expiry - datetime.now(timezone.utc)).total_seconds())
    return delta_seconds / 3600, int(delta_seconds % 3600 / 60)


class DeTradeTokenService:
    """Runtime service for updating the DeTrade WebSocket token.

    Usage (from a Telegram admin handler):
        result = DeTradeTokenService(db).update(raw_input, actor_telegram_id)
        if result.ok:
            await detrade_observer.restart_with_new_token()
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def update(self, raw_input: str, actor_telegram_id: int) -> TokenUpdateResult:
        """Parse raw_input, validate, persist, and return the result.

        raw_input may be:
          - A raw JWT string
          - A WebSocket URL with ?token= query parameter
          - A pasted cURL command or DevTools network request
        """
        token = _extract_jwt(raw_input.strip())
        if token is None:
            self._audit(actor_telegram_id, 'DETRADE_TOKEN_REJECTED', {'reason': 'no_jwt_found'})
            return TokenUpdateResult(
                ok=False,
                error='No JWT token found in the pasted text. Copy the full token starting with "eyJ..." and try again.',
                expires_at=None,
                remaining_hours=None,
                remaining_minutes=None,
            )

        if token.lower() in PLACEHOLDER_TOKENS:
            self._audit(actor_telegram_id, 'DETRADE_TOKEN_REJECTED', {'reason': 'placeholder_token'})
            return TokenUpdateResult(
                ok=False,
                error='That looks like a placeholder token, not a real one.',
                expires_at=None,
                remaining_hours=None,
                remaining_minutes=None,
            )

        if detrade_token_is_expired(token, now_seconds=time.time()):
            expiry = _token_expiry(token)
            self._audit(actor_telegram_id, 'DETRADE_TOKEN_REJECTED', {'reason': 'expired'})
            expired_at_str = expiry.strftime('%H:%M UTC %d %b') if expiry else 'unknown'
            return TokenUpdateResult(
                ok=False,
                error=f'This token has already expired ({expired_at_str}). Please grab a fresh one from your browser.',
                expires_at=expiry,
                remaining_hours=None,
                remaining_minutes=None,
            )

        expiry = _token_expiry(token)
        hours, minutes = _remaining(expiry) if expiry is not None else (0.0, 0)

        # Persist to DB so it survives restarts
        row = self.db.get(RuntimeSetting, DETRADE_TOKEN_KEY)
        if row is None:
            row = RuntimeSetting(key=DETRADE_TOKEN_KEY, value=token)
            self.db.add(row)
        else:
            row.value = token
        row.updated_by = actor_telegram_id
        self._audit(actor_telegram_id, 'DETRADE_TOKEN_UPDATED', {
            'expires_at': expiry.isoformat() if expiry else None,
            'remaining_hours': round(hours, 2),
        })
        self.db.commit()

        return TokenUpdateResult(
            ok=True,
            error=None,
            expires_at=expiry,
            remaining_hours=hours,
            remaining_minutes=minutes,
        )

    def get_persisted_token(self) -> str | None:
        """Return the database-stored token if present and not expired."""
        row = self.db.get(RuntimeSetting, DETRADE_TOKEN_KEY)
        if row is None:
            return None
        token = row.value.strip() if row.value else None
        if not token or detrade_token_is_expired(token):
            return None
        return token

    def _audit(self, actor: int, action: str, details: dict | None = None) -> None:
        self.db.add(AuditLog(
            actor_telegram_id=actor,
            action=action,
            target='detrade:token',
            details=details,
        ))
