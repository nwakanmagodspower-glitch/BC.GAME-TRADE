from __future__ import annotations

import asyncio

from sqlalchemy import select
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import (
    User,
    VerificationDelivery,
    VerificationDeliveryStatus,
    VerificationRequest,
    VerificationStatus,
    utcnow,
)

settings = get_settings()


class VerificationDeliveryWorker:
    """Retry owner packet delivery outside the webhook request path."""

    def __init__(self, poll_seconds: float = 2.0):
        self.poll_seconds = poll_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last_error: str | None = None

    async def start(self) -> None:
        if not settings.telegram_bot_token or not settings.owner_telegram_id:
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name='verification-delivery-worker')

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def run_once(self) -> None:
        if not settings.telegram_bot_token or not settings.owner_telegram_id:
            return
        with SessionLocal() as db:
            delivery = db.scalar(
                select(VerificationDelivery)
                .where(
                    VerificationDelivery.status.in_([
                        VerificationDeliveryStatus.PENDING,
                        VerificationDeliveryStatus.SENDING,
                        VerificationDeliveryStatus.FAILED,
                    ]),
                    VerificationDelivery.attempts < settings.verification_delivery_max_attempts,
                )
                .order_by(VerificationDelivery.id.asc())
                .with_for_update(skip_locked=True)
            )
            if delivery is None:
                return
            delivery.status = VerificationDeliveryStatus.SENDING
            delivery.attempts += 1
            db.commit()

            request = db.get(VerificationRequest, delivery.verification_request_id)
            user = db.get(User, request.user_id) if request else None
            if request is None or user is None or request.status != VerificationStatus.SUBMITTED:
                delivery.status = VerificationDeliveryStatus.FAILED
                delivery.last_error = 'packet_not_submitted'
                db.commit()
                return

            try:
                async with Bot(settings.telegram_bot_token) as bot:
                    await bot.send_photo(settings.owner_telegram_id, request.profile_proof_file_id, caption='BC.GAME profile proof')
                    for index, file_id in enumerate(request.deposit_proof_file_ids or [], start=1):
                        await bot.send_photo(settings.owner_telegram_id, file_id, caption=f'Deposit proof {index}')

                    username = f'@{user.telegram_username}' if user.telegram_username else 'None'
                    text = (
                        '🔐 NEW VERIFICATION REQUEST\n\n'
                        f'Request ID: {request.id}\n'
                        f'Name: {user.first_name or "Unknown"}\n'
                        f'Username: {username}\n'
                        f'Telegram ID: {user.telegram_user_id}\n'
                        f'BC.GAME User ID: {request.bcgame_user_id}\n\n'
                        'All evidence for this packet was delivered above. Check the BC.GAME affiliate dashboard before deciding.'
                    )
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton('✅ Approve', callback_data=f'admin:approve:{request.id}')],
                        [InlineKeyboardButton('🔄 Resubmit', callback_data=f'admin:resubmit:{request.id}')],
                        [InlineKeyboardButton('❌ Reject', callback_data=f'admin:reject:{request.id}')],
                    ])
                    await bot.send_message(settings.owner_telegram_id, text, reply_markup=keyboard)
                delivery.status = VerificationDeliveryStatus.SENT
                delivery.delivered_at = utcnow()
                delivery.last_error = None
            except Exception as exc:
                delivery.status = VerificationDeliveryStatus.FAILED
                delivery.last_error = type(exc).__name__
            db.commit()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = type(exc).__name__
            await asyncio.sleep(self.poll_seconds)


verification_delivery_worker = VerificationDeliveryWorker()
