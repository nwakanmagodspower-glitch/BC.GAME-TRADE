from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.bcgame_rounds import bcgame_round_service
from app.models.entities import Signal, User, UserStatus
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

    @staticmethod
    def _cooldown_active(user: User, now: datetime) -> bool:
        if user.last_scan_requested_at is None:
            return False
        previous = user.last_scan_requested_at
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        return (now - previous).total_seconds() < settings.signal_user_cooldown_seconds

    def _worker_ready(self) -> bool:
        if settings.app_env.lower() != 'production' or settings.run_background_jobs:
            return True
        worker = get_worker_status(self.db)
        return bool(worker.fresh and worker.healthy)

    async def request_scan(self, user_id: int, countdown_seconds: int | None = None) -> UserSignalResult:
        if settings.signal_mode.upper() != 'LIVE':
            return UserSignalResult(None, False, 'Signals are in PAPER validation mode and are not actionable.')

        # Read-only preflight. Do not hold a PostgreSQL row lock or transaction
        # while waiting on DeTrade/Binance/Bybit network work.
        user = self.db.scalar(select(User).where(User.id == user_id))
        if user is None or user.status != UserStatus.APPROVED or user.is_blocked:
            self.db.rollback()
            return UserSignalResult(None, False, 'Approved access is required.')

        enabled = AdminOpsService(self.db).get_bool(AdminOpsService.SIGNALS_ENABLED_KEY, default=settings.signals_enabled)
        if not enabled:
            self.db.rollback()
            return UserSignalResult(None, False, 'Signals are currently disabled.')

        if not self._worker_ready():
            self.db.rollback()
            return UserSignalResult(None, False, 'Signal service is refreshing. Please try again in a few seconds.')

        if self._cooldown_active(user, datetime.now(timezone.utc)):
            self.db.rollback()
            return UserSignalResult(None, False, 'Please wait briefly before scanning again.')

        # Release the read transaction before any network await.
        self.db.rollback()

        timing_mode = settings.signal_timing_mode.upper()
        round_snapshot = None
        trigger_mode = 'MANUAL_TRIGGER'

        if timing_mode == 'MANUAL_SYNC':
            pass
        elif timing_mode in {'HYBRID_SYNC', 'AUTO_SYNC'}:
            timing = await bcgame_round_service.current_round_decision()
            if timing.actionable and timing.snapshot is not None:
                round_snapshot = timing.snapshot
                trigger_mode = 'DETRADE_SYNC'
            elif timing.synchronized:
                return UserSignalResult(None, False, timing.reason)
            elif timing_mode == 'AUTO_SYNC':
                return UserSignalResult(None, False, 'Live BCGAME timing is refreshing. Wait for the next fresh round.')
            else:
                trigger_mode = 'MANUAL_FALLBACK'
        else:
            return UserSignalResult(None, False, 'Signal timing mode is unavailable.')

        seconds_until_start = None
        contract_duration_seconds = None
        if round_snapshot is not None:
            measurement_time = datetime.now(timezone.utc)
            seconds_until_start = max(0.0, round_snapshot.seconds_until_order_close(measurement_time))
            contract_duration_seconds = max(
                0.0,
                (round_snapshot.end_rate_at - round_snapshot.start_rate_at).total_seconds(),
            )

        intelligence = await signal_intelligence_service.scan(
            settings.analysis_pair,
            seconds_until_start=seconds_until_start,
            contract_duration_seconds=contract_duration_seconds,
        )
        if not intelligence.service_available:
            return UserSignalResult(None, False, 'Live BTC data is refreshing. Please try again in a few seconds.')

        if round_snapshot is not None:
            remaining_after_scan = round_snapshot.seconds_until_order_close(datetime.now(timezone.utc))
            if remaining_after_scan * 1000 <= settings.detrade_dispatch_min_remaining_ms:
                return UserSignalResult(None, False, 'This round moved too close to the cutoff while scanning. Skip it and use the next fresh round.')

        # Final atomic gate. Re-lock and re-check all mutable state, including the
        # cooldown, so simultaneous taps cannot create duplicate directional scans.
        user = self.db.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or user.status != UserStatus.APPROVED or user.is_blocked:
            self.db.rollback()
            return UserSignalResult(None, False, 'Approved access is required.')

        enabled = AdminOpsService(self.db).get_bool(AdminOpsService.SIGNALS_ENABLED_KEY, default=settings.signals_enabled)
        if not enabled or settings.signal_mode.upper() != 'LIVE':
            self.db.rollback()
            return UserSignalResult(None, False, 'Signals are currently disabled.')

        if not self._worker_ready():
            self.db.rollback()
            return UserSignalResult(None, False, 'Signal service is refreshing. Please try again in a few seconds.')

        now = datetime.now(timezone.utc)
        if self._cooldown_active(user, now):
            self.db.rollback()
            return UserSignalResult(None, False, 'A scan was just completed for your account. Please wait briefly before scanning again.')

        user.last_scan_requested_at = now
        signal = SignalRecordService(self.db).record_scan(
            intelligence,
            requested_by_user_id=user_id,
            round_snapshot=round_snapshot,
            trigger_mode=trigger_mode,
        )
        return UserSignalResult(signal, True, intelligence.reason)
