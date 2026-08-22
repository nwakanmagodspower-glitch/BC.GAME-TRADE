from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import (
    BCGameRound,
    Broadcast,
    BroadcastDelivery,
    BroadcastStatus,
    Signal,
    SignalNotification,
)
from app.models.webhook import TelegramUpdateReceipt

settings = get_settings()


@dataclass(frozen=True)
class CleanupResult:
    webhook_receipts: int
    signal_notifications: int
    signals: int
    bcgame_rounds: int
    broadcast_deliveries: int

    @property
    def total(self) -> int:
        return (
            self.webhook_receipts
            + self.signal_notifications
            + self.signals
            + self.bcgame_rounds
            + self.broadcast_deliveries
        )


class RetentionCleanupService:
    """Age-based cleanup for temporary operational and signal-intelligence records.

    User access/verification state is retained. Verification evidence is purged
    immediately after owner review. Generated signals/results are intelligence
    records with the configured retention window (10 days in the V1 Blueprint).
    """

    def __init__(self, retention_days: int | None = None, interval_seconds: int | None = None):
        self.retention_days = retention_days or settings.temporary_retention_days
        self.interval_seconds = interval_seconds or settings.cleanup_interval_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last_error: str | None = None
        self.last_run_at: datetime | None = None
        self.last_result: CleanupResult | None = None

    def cleanup_once(self, now: datetime | None = None) -> CleanupResult:
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self.retention_days)

        with SessionLocal() as db:
            webhook_result = db.execute(
                delete(TelegramUpdateReceipt).where(TelegramUpdateReceipt.received_at < cutoff)
            )

            old_signal_ids = select(Signal.id).where(Signal.created_at < cutoff)
            notification_result = db.execute(
                delete(SignalNotification).where(
                    (SignalNotification.created_at < cutoff)
                    | (SignalNotification.signal_id.in_(old_signal_ids))
                )
            )
            signal_result = db.execute(
                delete(Signal).where(Signal.created_at < cutoff)
            )
            round_result = db.execute(
                delete(BCGameRound).where(
                    BCGameRound.observed_at < cutoff,
                    ~exists(
                        select(Signal.id).where(Signal.bcgame_round_id == BCGameRound.id)
                    ),
                )
            )

            old_completed_broadcast_ids = select(Broadcast.id).where(
                Broadcast.status == BroadcastStatus.COMPLETE,
                Broadcast.completed_at.is_not(None),
                Broadcast.completed_at < cutoff,
            )
            delivery_result = db.execute(
                delete(BroadcastDelivery).where(
                    BroadcastDelivery.broadcast_id.in_(old_completed_broadcast_ids)
                )
            )
            db.commit()

            result = CleanupResult(
                webhook_receipts=int(webhook_result.rowcount or 0),
                signal_notifications=int(notification_result.rowcount or 0),
                signals=int(signal_result.rowcount or 0),
                bcgame_rounds=int(round_result.rowcount or 0),
                broadcast_deliveries=int(delivery_result.rowcount or 0),
            )

        self.last_run_at = now
        self.last_result = result
        return result

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name='retention-cleanup')

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.cleanup_once()
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f'{type(exc).__name__}: {exc}'
            await asyncio.sleep(self.interval_seconds)


retention_cleanup_service = RetentionCleanupService()
