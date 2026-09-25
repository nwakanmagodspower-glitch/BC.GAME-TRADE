from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings

settings = get_settings()
PLACEHOLDER_TOKENS = {'temporary', 'placeholder', '<temporary>', '<temporary token>'}


def detrade_token_is_expired(raw: str | None, *, now_seconds: float | None = None) -> bool:
    """Fail closed on a JWT whose signed expiry claim has elapsed.

    This does not authenticate the JWT or trust it for permissions. DeTrade still
    performs that verification. It only prevents a known-expired environment
    secret from being retried and reported as configured.
    """
    if not raw:
        return False
    parts = raw.strip().split('.')
    if len(parts) != 3:
        return False
    try:
        padded = parts[1] + ('=' * (-len(parts[1]) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded).decode('utf-8'))
        expires_at = float(payload['exp'])
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    current = time.time() if now_seconds is None else now_seconds
    return expires_at <= current


def usable_detrade_token(raw: str | None) -> str | None:
    """Return a configured secret only when it is not empty or a known placeholder."""
    if not raw:
        return None
    token = raw.strip()
    if (
        not token
        or token.lower() in PLACEHOLDER_TOKENS
        or detrade_token_is_expired(token)
    ):
        return None
    return token


@dataclass(frozen=True, repr=False)
class DeTradeCredentials:
    token: str
    account_type: int

    def __repr__(self) -> str:
        return 'DeTradeCredentials(token=<redacted>, account_type=<redacted>)'


class DeTradeTokenProvider(Protocol):
    async def get_credentials(self, *, force_refresh: bool = False) -> DeTradeCredentials | None: ...
    async def invalidate(self) -> None: ...


class EnvironmentDeTradeTokenProvider:
    """Production token provider.

    Priority order at each credential request:
      1. Database-persisted token (set via /set_token command) — survives restarts.
      2. DETRADE_WS_TOKEN environment variable — cold-start fallback.

    Once a token is rejected by DeTrade (codes 603/3100), invalidate() is called.
    The connection stays down until /set_token supplies a new valid token.
    """

    def __init__(self) -> None:
        self._invalidated = False
        # Injected at app startup to avoid circular imports.
        # Signature: () -> str | None
        self._db_token_getter = None

    def set_db_token_getter(self, getter) -> None:
        """Wire up the database token lookup after the service layer is ready."""
        self._db_token_getter = getter

    @staticmethod
    def _usable_token(raw: str | None) -> str | None:
        return usable_detrade_token(raw)

    async def get_credentials(self, *, force_refresh: bool = False) -> DeTradeCredentials | None:
        if self._invalidated:
            return None

        # 1. Database-persisted token wins (set via /set_token).
        if self._db_token_getter is not None:
            try:
                db_token = self._db_token_getter()
            except Exception:
                db_token = None
            if db_token:
                token = self._usable_token(db_token)
                if token:
                    return DeTradeCredentials(token=token, account_type=settings.detrade_client_type)

        # 2. Environment variable fallback (cold-start default).
        token = self._usable_token(settings.detrade_ws_token)
        if token is None:
            return None
        return DeTradeCredentials(token=token, account_type=settings.detrade_client_type)

    async def invalidate(self) -> None:
        # Block further use of the current token until /set_token provides a new one.
        # The /set_token handler resets this flag explicitly after persisting a valid token.
        self._invalidated = True


detrade_token_provider: DeTradeTokenProvider = EnvironmentDeTradeTokenProvider()
