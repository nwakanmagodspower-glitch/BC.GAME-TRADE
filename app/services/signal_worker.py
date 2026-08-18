from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Signal, SignalStatus
from app.services.signal_lifecycle import SignalLifecycleService
from app.services.signal_notifications import SignalNotificationService


class SignalLifecycleWorker:
    """Database-backed worker for signal lifecycle and Telegram state notifications."""

    def __init__(self, poll_seconds: float = 1.0):
        self.poll_seconds = poll_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last_error: str | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name='signal-lifecycle-worker')

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def run_once(self) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            signals = db.scalars(
                select(Signal)
                .where(Signal.status.in_([SignalStatus.WAITING_ENTRY, SignalStatus.ACTIVE]))
                .order_by(Signal.id.asc())
            ).all()
            lifecycle = SignalLifecycleService(db)
            notifications = SignalNotificationService(db)

            for signal in signals:
                previous = signal.status
                if signal.status == SignalStatus.WAITING_ENTRY:
                    await lifecycle.activate_if_due(signal, now=now)
                if signal.status != previous and signal.status in {SignalStatus.ACTIVE, SignalStatus.CANCELLED}:
                    await notifications.notify_status(signal)

                previous = signal.status
                if signal.status == SignalStatus.ACTIVE:
                    await lifecycle.settle_if_due(signal, now=now)
                if signal.status != previous and signal.status in {SignalStatus.WIN, SignalStatus.LOSS, SignalStatus.TIE, SignalStatus.CANCELLED}:
                    await notifications.notify_status(signal)

            # Retry any terminal/current state notification that previously failed.
            retryable = db.scalars(
                select(Signal)
                .where(Signal.status.in_([
                    SignalStatus.ACTIVE,
                    SignalStatus.CANCELLED,
                    SignalStatus.WIN,
                    SignalStatus.LOSS,
                    SignalStatus.TIE,
                ]))
                .order_by(Signal.id.desc())
                .limit(100)
            ).all()
            for signal in retryable:
                await notifications.notify_status(signal)

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f'{type(exc).__name__}: {exc}'
            await asyncio.sleep(self.poll_seconds)


signal_lifecycle_worker = SignalLifecycleWorker()
