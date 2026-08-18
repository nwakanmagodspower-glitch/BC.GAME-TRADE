from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Signal, SignalDirection, SignalStatus
from app.services.signal_intelligence import signal_intelligence_service
from app.services.signal_records import SignalRecordService

settings = get_settings()


@dataclass(frozen=True)
class UserSignalResult:
    signal: Signal | None
    available: bool
    reason: str


class UserSignalService:
    def __init__(self, db: Session):
        self.db = db

    async def request_scan(self, user_id: int) -> UserSignalResult:
        # Product kill switch remains authoritative even though the intelligence
        # engine can be exercised separately by research tooling.
        if not settings.signals_enabled:
            return UserSignalResult(None, False, 'Signals are currently disabled.')

        # Avoid stacking multiple live candidates for one user. This keeps the
        # on-demand UX simple and prevents accidental repeated-entry pressure.
        existing = self.db.scalar(
            select(Signal)
            .where(
                Signal.requested_by_user_id == user_id,
                Signal.status.in_([SignalStatus.WAITING_ENTRY, SignalStatus.ACTIVE]),
            )
            .order_by(Signal.id.desc())
        )
        if existing is not None:
            return UserSignalResult(existing, False, 'You already have a signal waiting or active.')

        intelligence = await signal_intelligence_service.scan(settings.default_pair)
        signal = SignalRecordService(self.db).record_scan(intelligence, requested_by_user_id=user_id)
        return UserSignalResult(signal, True, intelligence.reason)
