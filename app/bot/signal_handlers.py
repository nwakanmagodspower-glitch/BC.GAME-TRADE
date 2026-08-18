from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.handlers import _approved_menu
from app.bot.signal_views import build_scan_prompt_keyboard, build_signal_keyboard, format_signal
from app.core.database import SessionLocal
from app.models.entities import UserStatus
from app.services.onboarding import OnboardingService
from app.services.user_signals import UserSignalService


async def signal_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approved-user BTC signal UX; trading logic remains in application services."""
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return

    with SessionLocal() as db:
        user = OnboardingService(db).get_or_create_user(query.from_user)
        if user.status != UserStatus.APPROVED or user.is_blocked:
            await query.answer('Your approved access is required.', show_alert=True)
            return

        if query.data == 'menu:home':
            await query.answer()
            await query.message.reply_text('Choose an option below.', reply_markup=_approved_menu())
            return

        if query.data == 'menu:signal':
            await query.answer()
            await query.message.reply_text(
                '📊 BTC/USDT — BC.GAME UP/DOWN\n\n'
                'This is an on-demand scan. The engine can return UP, DOWN, or NO TRADE. '
                'A directional setup can still be cancelled before entry if conditions change.\n\n'
                'Tap Scan Now when you are ready.',
                reply_markup=build_scan_prompt_keyboard(),
            )
            return

        if query.data == 'menu:scan_now':
            await query.answer('Scanning BTC/USDT…')
            result = await UserSignalService(db).request_scan(user.id)
            if not result.available:
                await query.message.reply_text(result.reason, reply_markup=_approved_menu())
                return
            signal = result.signal
            await query.message.reply_text(
                format_signal(signal),
                reply_markup=build_signal_keyboard(signal.direction),
            )
