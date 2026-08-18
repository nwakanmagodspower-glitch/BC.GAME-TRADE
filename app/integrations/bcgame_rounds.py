from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class BCGameRoundSnapshot:
    round_id: str
    observed_at: datetime
    order_closes_at: datetime
    start_rate_at: datetime
    end_rate_at: datetime
    stake_band: str
    up_payout_pct: float | None = None
    down_payout_pct: float | None = None
    up_pool_amount: float | None = None
    down_pool_amount: float | None = None
    up_players: int | None = None
    down_players: int | None = None

    def seconds_until_order_close(self, now: datetime) -> float:
        return (self.order_closes_at - now).total_seconds()


class BCGameRoundService:
    """Boundary for BC.GAME's real round/countdown data.

    The observed game contract is known, but a trustworthy structured endpoint
    for live round state has not yet been integrated. This service intentionally
    fails closed until that integration exists. Do not replace it with guessed
    wall-clock alignment or screen scraping.
    """

    def __init__(self) -> None:
        self.last_error: str | None = None
        self.last_snapshot: BCGameRoundSnapshot | None = None

    async def current_actionable_round(self) -> BCGameRoundSnapshot | None:
        if not settings.bcgame_round_sync_enabled:
            self.last_error = 'BC.GAME round synchronization is not connected.'
            return None
        # Placeholder boundary: an authenticated/legitimate structured source
        # must populate this in a later milestone. LIVE startup is blocked until
        # round sync is explicitly enabled and this implementation is completed.
        self.last_error = 'BC.GAME round synchronization provider is not implemented yet.'
        return None


bcgame_round_service = BCGameRoundService()
