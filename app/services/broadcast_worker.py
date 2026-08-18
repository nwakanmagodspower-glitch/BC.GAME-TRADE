from __future__ import annotations

import asyncio
from sqlalchemy import func, select
from telegram import Bot

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import Broadcast, BroadcastDelivery, BroadcastStatus, DeliveryStatus, User, utcnow

settings = get_settings()


class BroadcastWorker:
    def __init__(self, batch_size: int = 20, poll_seconds: float = 2.0):
        self.batch_size = batch_size
        self.poll_seconds = poll_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last_error: str | None = None

    async def start(self):
        if not settings.telegram_bot_token or (self._task and not self._task.done()):
            return
        self._stop.clear(); self._task = asyncio.create_task(self._run(), name='broadcast-worker')

    async def stop(self):
        self._stop.set()
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass

    async def run_once(self):
        if not settings.telegram_bot_token: return
        bot = Bot(settings.telegram_bot_token)
        with SessionLocal() as db:
            broadcast = db.scalar(select(Broadcast).where(Broadcast.status.in_([BroadcastStatus.QUEUED, BroadcastStatus.SENDING])).order_by(Broadcast.id.asc()))
            if not broadcast: return
            broadcast.status = BroadcastStatus.SENDING; db.commit()
            deliveries = db.scalars(select(BroadcastDelivery).where(BroadcastDelivery.broadcast_id == broadcast.id, BroadcastDelivery.status == DeliveryStatus.PENDING).order_by(BroadcastDelivery.id.asc()).limit(self.batch_size)).all()
            for delivery in deliveries:
                user = db.get(User, delivery.user_id)
                delivery.attempts += 1
                try:
                    if not user:
                        raise RuntimeError('user_missing')
                    await bot.send_message(user.telegram_user_id, broadcast.message)
                    delivery.status = DeliveryStatus.SENT; delivery.sent_at = utcnow(); delivery.last_error = None
                except Exception as exc:
                    delivery.status = DeliveryStatus.FAILED; delivery.last_error = f'{type(exc).__name__}: {exc}'[:1000]
                await asyncio.sleep(0.05)
            db.commit()
            pending = int(db.scalar(select(func.count(BroadcastDelivery.id)).where(BroadcastDelivery.broadcast_id == broadcast.id, BroadcastDelivery.status == DeliveryStatus.PENDING)) or 0)
            sent = int(db.scalar(select(func.count(BroadcastDelivery.id)).where(BroadcastDelivery.broadcast_id == broadcast.id, BroadcastDelivery.status == DeliveryStatus.SENT)) or 0)
            failed = int(db.scalar(select(func.count(BroadcastDelivery.id)).where(BroadcastDelivery.broadcast_id == broadcast.id, BroadcastDelivery.status == DeliveryStatus.FAILED)) or 0)
            broadcast.sent_count = sent; broadcast.failed_count = failed
            if pending == 0:
                broadcast.status = BroadcastStatus.COMPLETE; broadcast.completed_at = utcnow()
            db.commit()

    async def _run(self):
        while not self._stop.is_set():
            try: await self.run_once(); self.last_error = None
            except asyncio.CancelledError: raise
            except Exception as exc: self.last_error = f'{type(exc).__name__}: {exc}'
            await asyncio.sleep(self.poll_seconds)


broadcast_worker = BroadcastWorker()
