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
            if not worker.fresh:
                return UserSignalResult(None, False, 'Signal service is temporarily unavailable. Please try again shortly.')

        existing = self.db.scalar(
            select(Signal).where(
                Signal.requested_by_user_id == user_id,
                Signal.status.in_([SignalStatus.WAITING_ENTRY, SignalStatus.ACTIVE]),
            ).order_by(Signal.id.desc())
        )
        if existing is not None:
            return UserSignalResult(existing, False, 'You already have a current-round signal waiting or active.')

        now = datetime.now(timezone.utc)
        if user.last_scan_requested_at is not None:
            previous = user.last_scan_requested_at
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            if (now - previous).total_seconds() < settings.signal_user_cooldown_seconds:
                return UserSignalResult(None, False, 'Please wait for the next fresh countdown before scanning again.')
        user.last_scan_requested_at = now
        self.db.commit()

        timing_mode = settings.signal_timing_mode.upper()
        if timing_mode == 'MANUAL_SYNC':
            if countdown_seconds is None or countdown_seconds not in settings.manual_countdowns():
                return UserSignalResult(None, False, 'Choose the button that matches the BC.GAME timer: 15, 14, 13, or 12 seconds.')
            observed_at = datetime.now(timezone.utc)
            round_snapshot = bcgame_round_service.manual_snapshot(countdown_seconds, observed_at=observed_at)
        elif timing_mode == 'AUTO_SYNC':
            round_snapshot = await bcgame_round_service.current_actionable_round()
            if round_snapshot is None:
                return UserSignalResult(None, False, 'Automatic BC.GAME round timing is unavailable. No signal was generated.')
        else:
            return UserSignalResult(None, False, 'Signal timing mode is unavailable.')

        intelligence = await signal_intelligence_service.scan(settings.analysis_pair)
        if not intelligence.service_available:
            return UserSignalResult(None, False, intelligence.reason)

        # In manual sync the user already confirmed a visible countdown. If
        # analysis/Telegram handling took too long, fail rather than provide a
        # late current-round signal.
        # Serialize the commit boundary per user and revalidate all revocable
        # controls after asynchronous market work.
        user = self.db.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or user.status != UserStatus.APPROVED or user.is_blocked:
            self.db.rollback()
            return UserSignalResult(None, False, 'Approved access is required.')
        enabled = AdminOpsService(self.db).get_bool(AdminOpsService.SIGNALS_ENABLED_KEY, default=settings.signals_enabled)
        if not enabled or settings.signal_mode.upper() != 'LIVE':
            self.db.rollback()
            return UserSignalResult(None, False, 'Signals are currently disabled.')
        existing = self.db.scalar(
            select(Signal).where(
                Signal.requested_by_user_id == user_id,
                Signal.status.in_([SignalStatus.WAITING_ENTRY, SignalStatus.ACTIVE]),
            ).order_by(Signal.id.desc())
        )
        if existing is not None:
            self.db.rollback()
            return UserSignalResult(existing, False, 'You already have a current-round signal waiting or active.')

        now = datetime.now(timezone.utc)
        remaining = round_snapshot.seconds_until_order_close(now)
        if remaining < settings.manual_sync_min_remaining_after_scan:
            self.db.rollback()
            return UserSignalResult(None, False, 'Too little time remains for this round. Skip it and scan the next fresh 15-second countdown.')

        signal = SignalRecordService(self.db).record_scan(intelligence, requested_by_user_id=user_id, round_snapshot=round_snapshot)
        return UserSignalResult(signal, True, intelligence.reason)
