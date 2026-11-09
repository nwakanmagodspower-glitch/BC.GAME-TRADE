from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import User, UserStatus

logger = logging.getLogger(__name__)
settings = get_settings()


class LeadFunnelScheduler:
    """Checks lead drop-offs every 15 minutes and sends targeted follow-up reminders."""

    def __init__(self, check_interval_seconds: int = 900):
        self.check_interval_seconds = check_interval_seconds
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self, bot) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(bot))
        logger.info("LeadFunnelScheduler started (15-min cadence).")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("LeadFunnelScheduler stopped.")

    async def check_and_send_reminders(self, bot) -> int:
        now = datetime.now(timezone.utc)
        sent_count = 0

        with SessionLocal() as db:
            # 1. 1_STARTED leads stuck > 30 minutes
            cutoff_started = now - timedelta(minutes=30)
            stuck_started = db.scalars(
                select(User)
                .where(
                    User.funnel_step == '1_STARTED',
                    User.step_updated_at <= cutoff_started,
                    User.status != UserStatus.SUSPENDED,
                    User.is_blocked.is_(False),
                )
            ).all()

            for user in stuck_started:
                if user.last_reminded_step == '1_STARTED':
                    continue
                first_name = user.first_name or "Trader"
                invite_link = settings.telegram_channel_invite_link
                if not invite_link and settings.telegram_channel_id:
                    ch = str(settings.telegram_channel_id)
                    if ch.startswith('@'):
                        invite_link = f"https://t.me/{ch[1:]}"
                
                keyboard = []
                if invite_link:
                    keyboard.append([InlineKeyboardButton("📢 Join Verification Channel", url=invite_link)])
                keyboard.append([InlineKeyboardButton("🔄 Verify Channel Access", callback_data="gate:check")])

                text = (
                    f"👋 Quick Reminder {first_name}!\n\n"
                    "Your Agentic AI Scanner terminal setup is incomplete.\n\n"
                    "Join our official VIP channel below to unlock universal 5-second Bitcoin signals "
                    "and claim your 100% Free Trial today!"
                )
                try:
                    await bot.send_message(
                        chat_id=user.telegram_user_id,
                        text=text,
                        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                    )
                    user.last_reminded_step = '1_STARTED'
                    user.last_reminded_at = now
                    sent_count += 1
                except Exception as exc:
                    logger.debug(f"Failed to send 1_STARTED reminder to {user.telegram_user_id}: {exc}")

            # 2. 2_CHANNEL_JOINED leads stuck > 4 hours
            cutoff_joined = now - timedelta(hours=4)
            stuck_joined = db.scalars(
                select(User)
                .where(
                    User.funnel_step == '2_CHANNEL_JOINED',
                    User.step_updated_at <= cutoff_joined,
                    User.status == UserStatus.PENDING,
                    User.is_blocked.is_(False),
                )
            ).all()

            for user in stuck_joined:
                if user.last_reminded_step == '2_CHANNEL_JOINED':
                    continue
                first_name = user.first_name or "Trader"
                text = (
                    f"⚡ Hey {first_name}!\n\n"
                    "You've unlocked the channel! 🎯\n\n"
                    "To activate your automated AI scanner terminal and receive high-accuracy 5-second signals, "
                    "please submit your numeric BCGAME User ID here.\n\n"
                    "📍 Find it: Open BCGAME → Tap Profile icon at top right → Copy numeric ID."
                )
                try:
                    await bot.send_message(chat_id=user.telegram_user_id, text=text)
                    user.last_reminded_step = '2_CHANNEL_JOINED'
                    user.last_reminded_at = now
                    sent_count += 1
                except Exception as exc:
                    logger.debug(f"Failed to send 2_CHANNEL_JOINED reminder to {user.telegram_user_id}: {exc}")

            # 3. 3_UID_SUBMITTED leads stuck > 18 hours
            cutoff_uid = now - timedelta(hours=18)
            stuck_uid = db.scalars(
                select(User)
                .where(
                    User.funnel_step == '3_UID_SUBMITTED',
                    User.step_updated_at <= cutoff_uid,
                    User.status == UserStatus.PENDING,
                    User.is_blocked.is_(False),
                )
            ).all()

            for user in stuck_uid:
                if user.last_reminded_step == '3_UID_SUBMITTED':
                    continue
                first_name = user.first_name or "Trader"
                text = (
                    f"⏳ VIP Terminal Update {first_name}!\n\n"
                    "We have your BCGAME User ID on file. If you haven't uploaded your deposit proof screenshot, "
                    "please send it now so we can approve your VIP terminal access!\n\n"
                    "Remember: your deposit stays 100% in YOUR wallet to trade with and withdraw anytime."
                )
                try:
                    await bot.send_message(chat_id=user.telegram_user_id, text=text)
                    user.last_reminded_step = '3_UID_SUBMITTED'
                    user.last_reminded_at = now
                    sent_count += 1
                except Exception as exc:
                    logger.debug(f"Failed to send 3_UID_SUBMITTED reminder to {user.telegram_user_id}: {exc}")

            if sent_count > 0:
                db.commit()

        return sent_count

    async def _run_loop(self, bot) -> None:
        while self._running:
            try:
                await self.check_and_send_reminders(bot)
            except Exception as exc:
                logger.error(f"Error in lead funnel reminder loop: {exc}")
            try:
                await asyncio.sleep(self.check_interval_seconds)
            except asyncio.CancelledError:
                break


lead_funnel_scheduler = LeadFunnelScheduler()
