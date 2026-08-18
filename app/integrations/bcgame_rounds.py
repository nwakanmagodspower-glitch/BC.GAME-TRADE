from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

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


@dataclass(frozen=True)
class BCGameRoundStatus:
    enabled: bool
    seen: bool
    fresh: bool
    age_seconds: float | None
    round_id: str | None
    last_error: str | None


class BCGameRoundService:
    """Boundary for BC.GAME's real round/countdown data.

    A trustworthy structured round provider has not yet been integrated. This
    boundary therefore fails closed and never substitutes guessed wall-clock
    timing or UI pixel scraping for real round state.
    """

    def __init__(self) -> None:
        self.last_error: str | None = None
        self.last_snapshot: BCGameRoundSnapshot | None = None

    def status(self, now: datetime | None = None) -> BCGameRoundStatus:
        if not settings.bcgame_round_sync_enabled:
            return BCGameRoundStatus(False, False, False, None, None, 'BC.GAME round synchronization is not connected.')
        snapshot = self.last_snapshot
        if snapshot is None:
            return BCGameRoundStatus(True, False, False, None, None, self.last_error or 'No BC.GAME round snapshot has been observed.')
        current = now or datetime.now(timezone.utc)
        observed = snapshot.observed_at if snapshot.observed_at.tzinfo else snapshot.observed_at.replace(tzinfo=timezone.utc)
        age = max(0.0, (current - observed.astimezone(timezone.utc)).total_seconds())
        fresh = age <= settings.bcgame_round_sync_max_age_seconds
        return BCGameRoundStatus(True, True, fresh, age, snapshot.round_id, self.last_error)

    async def current_actionable_round(self) -> BCGameRoundSnapshot | None:
        if not settings.bcgame_round_sync_enabled:
            self.last_error = 'BC.GAME round synchronization is not connected.'
            return None
        # Placeholder boundary: a legitimate/reliable structured source must
        # populate last_snapshot in the next milestone.
        self.last_error = 'BC.GAME round synchronization provider is not implemented yet.'
        return None


bcgame_round_service = BCGameRoundService()
