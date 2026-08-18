from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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
    source: str = 'AUTO_SYNC'
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
    """Boundary for automatic BC.GAME/DeTrade structured round data.

    AUTO_SYNC intentionally fails closed until a trustworthy structured source
    is integrated. MANUAL_SYNC does not call this provider; it builds an
    estimated round from the countdown value the user confirms in Telegram.
    """

    def __init__(self) -> None:
        self.last_error: str | None = None
        self.last_snapshot: BCGameRoundSnapshot | None = None

    def status(self, now: datetime | None = None) -> BCGameRoundStatus:
        if not settings.bcgame_round_sync_enabled:
            return BCGameRoundStatus(False, False, False, None, None, 'Automatic BC.GAME round synchronization is not connected.')
        snapshot = self.last_snapshot
        if snapshot is None:
            return BCGameRoundStatus(True, False, False, None, None, self.last_error or 'No automatic BC.GAME round snapshot has been observed.')
        current = now or datetime.now(timezone.utc)
        observed = snapshot.observed_at if snapshot.observed_at.tzinfo else snapshot.observed_at.replace(tzinfo=timezone.utc)
        age = max(0.0, (current - observed.astimezone(timezone.utc)).total_seconds())
        fresh = age <= settings.bcgame_round_sync_max_age_seconds
        return BCGameRoundStatus(True, True, fresh, age, snapshot.round_id, self.last_error)

    async def current_actionable_round(self) -> BCGameRoundSnapshot | None:
        if not settings.bcgame_round_sync_enabled:
            self.last_error = 'Automatic BC.GAME round synchronization is not connected.'
            return None
        self.last_error = 'Automatic BC.GAME round synchronization provider is not implemented yet.'
        return None

    def manual_snapshot(self, countdown_seconds: int, observed_at: datetime | None = None) -> BCGameRoundSnapshot:
        if countdown_seconds not in settings.manual_countdowns():
            raise ValueError('Unsupported manual countdown value.')
        now = observed_at or datetime.now(timezone.utc)
        start_at = now + timedelta(seconds=countdown_seconds)
        end_at = start_at + timedelta(seconds=settings.default_expiry_seconds)
        # This ID is deliberately labelled manual; it is not represented as a
        # BC.GAME-issued round identifier.
        round_id = f'manual-{int(now.timestamp() * 1000)}-{countdown_seconds}'
        return BCGameRoundSnapshot(
            round_id=round_id,
            observed_at=now,
            order_closes_at=start_at,
            start_rate_at=start_at,
            end_rate_at=end_at,
            stake_band=settings.default_stake_band,
            source='MANUAL_SYNC',
        )


bcgame_round_service = BCGameRoundService()
