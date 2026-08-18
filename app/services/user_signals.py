from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Signal, SignalStatus
from app.services.admin_ops import AdminOpsService
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
        enabled = AdminOpsService(self.db).get_bool(
            AdminOpsService.SIGNALS_ENABLED_KEY,
            default=settings.signals_enabled,
        )
        if not enabled:
            return UserSignalResult(None, False, 'Signals are currently disabled.')

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
        if not intelligence.service_available:
            # UNAVAILABLE is a request/runtime state, not a strategy NO_TRADE.
            # Do not contaminate strategy statistics with provider failures.
            return UserSignalResult(None, False, intelligence.reason)

        signal = SignalRecordService(self.db).record_scan(intelligence, requested_by_user_id=user_id)
        return UserSignalResult(signal, True, intelligence.reason)
