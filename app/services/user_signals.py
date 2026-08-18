from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.bcgame_rounds import bcgame_round_service
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
            return UserSignalResult(existing, False, 'You already have a BC.GAME round signal waiting or active.')

        # A user-facing five-second signal is meaningful only when we know the
        # real BC.GAME order window and first/second flag timestamps. Never
        # recreate the old next-minute approximation.
        round_snapshot = await bcgame_round_service.current_actionable_round()
        if round_snapshot is None:
            return UserSignalResult(
                None,
                False,
                'BC.GAME round timing is not synchronized yet. No actionable signal was generated.',
            )

        now = datetime.now(timezone.utc)
        if round_snapshot.seconds_until_order_close(now) < settings.signal_minimum_action_lead_seconds:
            return UserSignalResult(None, False, 'This round is too close to locking. Wait for the next round.')

        intelligence = await signal_intelligence_service.scan(settings.analysis_pair)
        if not intelligence.service_available:
            return UserSignalResult(None, False, intelligence.reason)

        signal = SignalRecordService(self.db).record_scan(
            intelligence,
            requested_by_user_id=user_id,
            round_snapshot=round_snapshot,
        )
        return UserSignalResult(signal, True, intelligence.reason)
