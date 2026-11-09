from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import get_settings
from app.models.entities import SignalDirection
from app.services.market_data import market_data_service
from app.services.signal_intelligence import signal_intelligence_service

logger = logging.getLogger(__name__)
settings = get_settings()


class ChannelLiveBroadcaster:
    """Async channel broadcast manager for 15-second live rounds on CHANNEL_ID."""

    def __init__(self):
        self.session_streak: int = 0
        self._running: bool = False
        self._task: asyncio.Task | None = None
        self._last_broadcast_at: datetime | None = None
        self._bot_username: str | None = None

    async def get_bot_username(self, bot: Bot) -> str:
        if not self._bot_username:
            try:
                me = await bot.get_me()
                self._bot_username = me.username or "bcgame_ai_bot"
            except Exception:
                self._bot_username = "bcgame_ai_bot"
        return self._bot_username

    async def start(self, bot: Bot) -> None:
        if self._running:
            return
        if not settings.telegram_channel_id:
            logger.info("ChannelLiveBroadcaster skipped: telegram_channel_id not configured.")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(bot))
        logger.info(f"ChannelLiveBroadcaster started for channel {settings.telegram_channel_id}.")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ChannelLiveBroadcaster stopped.")

    async def broadcast_live_round(
        self,
        bot: Bot,
        channel_id: int | str,
        direction: SignalDirection,
        entry_price: float,
    ) -> bool:
        """Executes the exact 15-second countdown & edit loop on CHANNEL_ID."""
        try:
            bot_username = await self.get_bot_username(bot)
            bot_link = f"https://t.me/{bot_username}?start=channel_live"
            dir_str = direction.value
            icon = "🟢" if direction == SignalDirection.UP else "🔴"

            # 1. Send initial 15s countdown message
            initial_text = (
                "📡 AGENTIC AI — LIVE ROUND\n\n"
                "⏱️ Countdown: 15s\n"
                f"🎯 Signal: {icon} {dir_str}\n"
                f"💰 Entry: ${entry_price:,.2f}\n\n"
                "⚡ Universal Round ($1–$50, $50–$100, $100–$200+)"
            )
            msg = await bot.send_message(chat_id=channel_id, text=initial_text)
            self._last_broadcast_at = datetime.now(timezone.utc)

            # 2. Wait 10 seconds -> Update countdown to 5 seconds
            await asyncio.sleep(10)
            update_5s_text = (
                "📡 AGENTIC AI — LIVE ROUND\n\n"
                "🔥 Locking Result In: 5 Seconds...\n"
                f"🎯 Signal: {icon} {dir_str}\n"
                f"💰 Entry: ${entry_price:,.2f}\n\n"
                "⚡ Universal Round — Result locking at 0:00..."
            )
            try:
                await bot.edit_message_text(
                    chat_id=channel_id,
                    message_id=msg.message_id,
                    text=update_5s_text,
                )
            except Exception as exc:
                logger.debug(f"Failed to edit 5s countdown: {exc}")

            # 3. Wait 5 seconds -> Fetch closing price & evaluate result
            await asyncio.sleep(5)
            snapshot = await market_data_service.cache.get_snapshot(
                settings.analysis_pair,
                settings.market_data_max_age_seconds,
            )
            close_price = snapshot.price if snapshot else entry_price

            # Under BC.Game Up/Down rules:
            # End Rate > Start Rate -> UP wins
            # End Rate <= Start Rate -> DOWN wins
            if close_price > entry_price:
                round_winner = SignalDirection.UP
            else:
                round_winner = SignalDirection.DOWN

            signal_won = (direction == round_winner)
            if signal_won:
                self.session_streak += 1
                result_header = f"✅ ROUND FINISHED — {direction.value} WON!"
            else:
                self.session_streak = 0
                result_header = f"🏁 ROUND FINISHED — {round_winner.value} WON"

            diff = close_price - entry_price
            diff_str = f"+${diff:.2f}" if diff >= 0 else f"-${abs(diff):.2f}"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ Launch On-Demand AI Scanner", url=bot_link)]
            ])

            final_text = (
                f"{result_header}\n\n"
                f"🎯 Signal: {icon} {dir_str}\n"
                f"💰 Entry: ${entry_price:,.2f}\n"
                f"🏁 Close: ${close_price:,.2f} ({diff_str})\n"
                f"🔥 Current Session Streak: {self.session_streak} WINS\n\n"
                "⚡ All rooms settled ($1–$50, $50–$100, $100–$200+)"
            )

            await bot.edit_message_text(
                chat_id=channel_id,
                message_id=msg.message_id,
                text=final_text,
                reply_markup=keyboard,
            )
            return True
        except Exception as exc:
            logger.error(f"Error in broadcast_live_round: {exc}")
            return False

    async def _run_loop(self, bot: Bot) -> None:
        while self._running:
            try:
                if settings.telegram_channel_id:
                    now = datetime.now(timezone.utc)
                    min_interval = settings.channel_broadcast_interval_seconds
                    can_broadcast = (
                        self._last_broadcast_at is None
                        or (now - self._last_broadcast_at).total_seconds() >= min_interval
                    )
                    if can_broadcast:
                        # Scan live market intelligence for high-confidence trend windows
                        intel = await signal_intelligence_service.scan(settings.analysis_pair)
                        if (
                            intel.service_available
                            and intel.direction in (SignalDirection.UP, SignalDirection.DOWN)
                            and intel.decision
                            and intel.decision.quality in ('STRONG', 'CONFIRMED')
                            and abs(intel.decision.bull_score - intel.decision.bear_score) >= 3
                        ):
                            snapshot = await market_data_service.cache.get_snapshot(
                                settings.analysis_pair,
                                settings.market_data_max_age_seconds,
                            )
                            if snapshot and snapshot.fresh:
                                await self.broadcast_live_round(
                                    bot=bot,
                                    channel_id=settings.telegram_channel_id,
                                    direction=intel.direction,
                                    entry_price=snapshot.price,
                                )
            except Exception as exc:
                logger.error(f"Error in channel broadcaster loop: {exc}")

            try:
                await asyncio.sleep(20)
            except asyncio.CancelledError:
                break


channel_live_broadcaster = ChannelLiveBroadcaster()

