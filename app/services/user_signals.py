from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Signal, SignalStatus, User, UserStatus
from app.services.admin_ops import AdminOpsService
from app.services.signal_intelligence import signal_intelligence_service
from app.services.signal_records import SignalRecordService
from app.services.worker_status import get_worker_status

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
        user = self.db.get(User, user_id)
        if user is None or user.status != UserStatus.APPROVED or user.is_blocked:
            return UserSignalResult(None, False, 'Approved access is required.')

        enabled = AdminOpsService(self.db).get_bool(
            AdminOpsService.SIGNALS_ENABLED_KEY,
            default=settings.signals_enabled,
        )
        if not enabled:
            return UserSignalResult(None, False, 'Signals are currently disabled.')

        # In the production separated topology a healthy background worker is a
        # hard dependency: it owns entry revalidation, settlement and lifecycle
        # notifications. Do not create a waiting signal when that worker is down.
        if settings.app_env.lower() == 'production' and not settings.run_background_jobs:
            worker = get_worker_status(self.db)
            if not worker.fresh:
                return UserSignalResult(None, False, 'Signal service is temporarily unavailable. Please try again shortly.')

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
            return UserSignalResult(None, False, intelligence.reason)

        signal = SignalRecordService(self.db).record_scan(intelligence, requested_by_user_id=user_id)
        return UserSignalResult(signal, True, intelligence.reason)
