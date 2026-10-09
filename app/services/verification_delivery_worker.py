from __future__ import annotations

import asyncio

from sqlalchemy import select
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

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
                    username = f'@{user.telegram_username}' if user.telegram_username else 'Not set'
                    tier_line = f'⭐ Selected Tier: {request.admin_note}\n' if request.admin_note else ''
                    caption = (
                        '🔐 NEW VERIFICATION\n\n'
                        f'👤 {user.first_name or "Unknown"} • {username}\n'
                        f'🆔 Telegram: {user.telegram_user_id}\n'
                        f'🎮 BCGAME ID: {request.bcgame_user_id}\n'
                        f'📦 Request #{request.id}\n'
                        f'{tier_line}'
                        '💰 Required deposit: ₦15,000+ ($10+)\n\n'
                        'Photo 1: BCGAME profile\n'
                        'Photo 2+: Deposit proof\n\n'
                        'Confirm registration and the ₦15,000+ ($10+) deposit in your affiliate dashboard before approving.'
                    )
                    proof_ids = [request.profile_proof_file_id, *(request.deposit_proof_file_ids or [])]
                    proof_ids = [file_id for file_id in proof_ids if file_id]
                    if len(proof_ids) >= 2:
                        media = [InputMediaPhoto(media=proof_ids[0], caption=caption)]
                        media.extend(InputMediaPhoto(media=file_id) for file_id in proof_ids[1:10])
                        await bot.send_media_group(settings.owner_telegram_id, media=media)
                    elif proof_ids:
                        await bot.send_photo(settings.owner_telegram_id, proof_ids[0], caption=caption)
                    else:
                        raise ValueError('verification_packet_has_no_evidence')

                    keyboard = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton('✅ Approve', callback_data=f'admin:approve:{request.id}'),
                            InlineKeyboardButton('❌ Reject', callback_data=f'admin:reject:{request.id}'),
                        ],
                        [InlineKeyboardButton('🔄 Ask to Resubmit', callback_data=f'admin:resubmit:{request.id}')],
                    ])
                    await bot.send_message(settings.owner_telegram_id, f'👆 Review Request #{request.id}', reply_markup=keyboard)
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
