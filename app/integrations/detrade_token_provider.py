from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings

settings = get_settings()
PLACEHOLDER_TOKENS = {'temporary', 'placeholder', '<temporary>', '<temporary token>'}


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
        if not raw:
            return None
        token = raw.strip()
        if not token or token.lower() in PLACEHOLDER_TOKENS:
            return None
        return token

    async def get_credentials(self, *, force_refresh: bool = False) -> DeTradeCredentials | None:
        # Environment values cannot be refreshed in-process. force_refresh is kept
        # on the interface so an official provider can replace this implementation.
        if self._invalidated and not force_refresh:
            return None
        token = self._usable_token(settings.detrade_ws_token)
        if token is None:
            return None
        if force_refresh:
            self._invalidated = False
        return DeTradeCredentials(token=token, account_type=settings.detrade_client_type)

    async def invalidate(self) -> None:
        self._invalidated = True


detrade_token_provider: DeTradeTokenProvider = EnvironmentDeTradeTokenProvider()
