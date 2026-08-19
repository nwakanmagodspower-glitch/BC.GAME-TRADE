from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.database import engine
from app.services.broadcast_worker import broadcast_worker
from app.services.retention_cleanup import retention_cleanup_service
from app.services.signal_worker import signal_lifecycle_worker
from app.services.verification_delivery_worker import verification_delivery_worker


class BackgroundJobCoordinator:
    """Ensure only one web process runs singleton background loops.

    Render zero-downtime deploys can temporarily overlap the old and new web
    instances. A PostgreSQL advisory lock lets only one process own lifecycle,
    broadcast, and cleanup work at a time. A replacement instance keeps trying
    and takes over shortly after the previous instance releases the lock.
    """

    LOCK_KEY = 0x424347414D455452  # stable app-specific 64-bit advisory-lock key

    def __init__(self, retry_seconds: float = 3.0):
        self.retry_seconds = retry_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._connection: Connection | None = None
        self.is_leader = False
        self.last_error: str | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name='background-job-coordinator')

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._relinquish()

    async def _become_leader(self) -> None:
        await signal_lifecycle_worker.start()
        await broadcast_worker.start()
        await verification_delivery_worker.start()
        await retention_cleanup_service.start()
        self.is_leader = True

    async def _relinquish(self) -> None:
        if self.is_leader:
            await retention_cleanup_service.stop()
            await broadcast_worker.stop()
            await verification_delivery_worker.stop()
            await signal_lifecycle_worker.stop()
            self.is_leader = False
        if self._connection is not None:
            try:
                self._connection.execute(
                    text('SELECT pg_advisory_unlock(:key)'), {'key': self.LOCK_KEY}
                )
            except Exception:
                pass
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    def _try_lock(self) -> bool:
        if engine.dialect.name != 'postgresql':
            # Local/test environments normally run a single process.
            return True
        self._connection = engine.connect()
        acquired = bool(
            self._connection.execute(
                text('SELECT pg_try_advisory_lock(:key)'), {'key': self.LOCK_KEY}
            ).scalar()
        )
        if not acquired:
            self._connection.close()
            self._connection = None
        return acquired

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.is_leader:
                    if self._try_lock():
                        await self._become_leader()
                elif self._connection is not None:
                    # Verify the lock-holding DB connection is still alive.
                    self._connection.execute(text('SELECT 1'))
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f'{type(exc).__name__}: {exc}'
                await self._relinquish()
            await asyncio.sleep(self.retry_seconds)


background_job_coordinator = BackgroundJobCoordinator()
