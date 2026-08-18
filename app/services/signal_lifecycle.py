from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Signal, SignalDirection, SignalStatus
from app.services.market_data import market_data_service

settings = get_settings()


class SignalLifecycleService:
    def __init__(self, db: Session):
        self.db = db

    async def activate_if_due(self, signal: Signal, now: datetime | None = None) -> Signal:
        if signal.status != SignalStatus.WAITING_ENTRY:
            return signal
        if signal.direction not in {SignalDirection.UP, SignalDirection.DOWN}:
            return signal
        if not signal.entry_window_start or not signal.entry_window_end:
            signal.status = SignalStatus.CANCELLED
            signal.decision_reason = 'Signal timing is incomplete.'
            self.db.commit()
            return signal

        current = now or datetime.now(timezone.utc)
        if current < signal.entry_window_start:
            return signal
        if current > signal.entry_window_end:
            signal.status = SignalStatus.CANCELLED
            signal.decision_reason = 'Entry window expired before activation.'
            self.db.commit()
            return signal

        snapshot = await market_data_service.cache.get_snapshot(
            signal.market,
            max_age_seconds=settings.market_data_max_age_seconds,
        )
        if snapshot is None or not snapshot.fresh:
            signal.status = SignalStatus.CANCELLED
            signal.decision_reason = 'Fresh market data was unavailable at entry.'
            self.db.commit()
            return signal

        signal.reference_entry_price = snapshot.price
        signal.status = SignalStatus.ACTIVE
        self.db.commit()
        self.db.refresh(signal)
        return signal
