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
    """Development/manual-test provider.

    This never obtains credentials itself. It only exposes a token already supplied
    securely to the process environment. The final production refresh path must use
    an authorized BCGAME tradingLogin -> DeTrade login/verify integration.
    """

    def __init__(self) -> None:
        self._invalidated = False

    @staticmethod
    def _usable_token(raw: str | None) -> str | None:
        return usable_detrade_token(raw)

    async def get_credentials(self, *, force_refresh: bool = False) -> DeTradeCredentials | None:
        # Environment values cannot be refreshed in-process. force_refresh is kept
        # on the interface so an official provider can replace this implementation.
        # An environment value cannot change inside a running Render process.
        # Never revive the same token after the server has rejected it. Rotating
        # the Render secret restarts the service and creates a new provider.
        if self._invalidated:
            return None
        token = self._usable_token(settings.detrade_ws_token)
        if token is None:
            return None
        return DeTradeCredentials(token=token, account_type=settings.detrade_client_type)

    async def invalidate(self) -> None:
        self._invalidated = True


detrade_token_provider: DeTradeTokenProvider = EnvironmentDeTradeTokenProvider()
