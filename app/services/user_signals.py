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

    async def request_scan(self, user_id: int, countdown_seconds: int | None = None) -> UserSignalResult:
        if settings.signal_mode.upper() != 'LIVE':
            return UserSignalResult(None, False, 'Signals are in PAPER validation mode and are not actionable.')

        user = self.db.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or user.status != UserStatus.APPROVED or user.is_blocked:
            return UserSignalResult(None, False, 'Approved access is required.')

        enabled = AdminOpsService(self.db).get_bool(AdminOpsService.SIGNALS_ENABLED_KEY, default=settings.signals_enabled)
        if not enabled:
            return UserSignalResult(None, False, 'Signals are currently disabled.')

        if settings.app_env.lower() == 'production' and not settings.run_background_jobs:
            worker = get_worker_status(self.db)
            if not worker.fresh or not worker.healthy:
                return UserSignalResult(None, False, 'Signal service is temporarily unavailable. Please try again shortly.')

        now = datetime.now(timezone.utc)
        if user.last_scan_requested_at is not None:
            previous = user.last_scan_requested_at
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            if (now - previous).total_seconds() < settings.signal_user_cooldown_seconds:
                return UserSignalResult(None, False, 'Please wait briefly before scanning again.')

        # MANUAL_SYNC no longer asks the user to guess 15/14/13/12. The button
        # press itself is the observed scan event. Until a genuine BCGAME round
        # feed exists, we do not invent a Start Rate timestamp or countdown.
        timing_mode = settings.signal_timing_mode.upper()
        if timing_mode == 'MANUAL_SYNC':
            round_snapshot = None
        elif timing_mode == 'AUTO_SYNC':
            round_snapshot = await bcgame_round_service.current_actionable_round()
            if round_snapshot is None:
                return UserSignalResult(None, False, 'Automatic BCGAME round timing is unavailable. No signal was generated.')
        else:
            return UserSignalResult(None, False, 'Signal timing mode is unavailable.')

        intelligence = await signal_intelligence_service.scan(settings.analysis_pair)
        if not intelligence.service_available:
            return UserSignalResult(None, False, intelligence.reason)

        # Recheck authorization and service state after analysis so a user cannot
        # retain a signal if access changes while the scan is being computed.
        user = self.db.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or user.status != UserStatus.APPROVED or user.is_blocked:
            self.db.rollback()
            return UserSignalResult(None, False, 'Approved access is required.')
        enabled = AdminOpsService(self.db).get_bool(AdminOpsService.SIGNALS_ENABLED_KEY, default=settings.signals_enabled)
        if not enabled or settings.signal_mode.upper() != 'LIVE':
            self.db.rollback()
            return UserSignalResult(None, False, 'Signals are currently disabled.')
        if settings.app_env.lower() == 'production' and not settings.run_background_jobs:
            worker = get_worker_status(self.db)
            if not worker.fresh or not worker.healthy:
                self.db.rollback()
                return UserSignalResult(None, False, 'Signal service is temporarily unavailable. Please try again shortly.')

        # Consume cooldown only after a valid market analysis is available.
        user.last_scan_requested_at = datetime.now(timezone.utc)
        signal = SignalRecordService(self.db).record_scan(
            intelligence,
            requested_by_user_id=user_id,
            round_snapshot=round_snapshot,
            trigger_mode='MANUAL_TRIGGER' if timing_mode == 'MANUAL_SYNC' else 'AUTO_SYNC',
        )
        return UserSignalResult(signal, True, intelligence.reason)
