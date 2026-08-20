from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.entities import RuntimeSetting


class WorkerHeartbeatService:
    KEY = 'background_worker_heartbeat'

    def __init__(self, interval_seconds: float = 10.0, health_provider: Callable[[], dict] | None = None):
        self.interval_seconds = interval_seconds
        self.health_provider = health_provider
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last_error: str | None = None

    def beat_once(self) -> None:
        now = datetime.now(timezone.utc)
        components = self.health_provider() if self.health_provider else {}
        healthy = all(bool(value) for value in components.values()) if components else True
        payload = json.dumps({
            'timestamp': now.isoformat(),
            'healthy': healthy,
            'components': components,
        }, separators=(',', ':'), sort_keys=True)
        with SessionLocal() as db:
            record = db.get(RuntimeSetting, self.KEY)
            if record is None:
                record = RuntimeSetting(key=self.KEY, value=payload)
                db.add(record)
            else:
                record.value = payload
                record.updated_at = now
            db.commit()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name='worker-heartbeat')

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
                self.beat_once()
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f'{type(exc).__name__}: {exc}'
            await asyncio.sleep(self.interval_seconds)


worker_heartbeat_service = WorkerHeartbeatService()
