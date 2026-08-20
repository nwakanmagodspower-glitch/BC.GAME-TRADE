from telegram import Update
from telegram.ext import ContextTypes

from app.bot.signal_views import build_scan_prompt_keyboard, build_signal_keyboard, format_signal
from app.core.database import SessionLocal
from app.models.entities import UserStatus
from app.services.onboarding import OnboardingService
from app.services.user_signals import UserSignalService


async def manual_scan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return
    try:
        countdown = int(query.data.rsplit(':', 1)[1])
    except (ValueError, IndexError):
        await query.answer('Invalid timer selection.', show_alert=True)
        return

    await query.answer(f'Scanning at {countdown}s…')
    with SessionLocal() as db:
        user = OnboardingService(db).get_or_create_user(query.from_user)
        if user.status != UserStatus.APPROVED or user.is_blocked:
            await query.message.reply_text('Approved access is required.')
            return

        result = await UserSignalService(db).request_scan(user.id, countdown_seconds=countdown)
        if not result.available or result.signal is None:
            await query.message.reply_text(result.reason, reply_markup=build_scan_prompt_keyboard())
            return

        await query.message.reply_text(
            format_signal(result.signal),
            reply_markup=build_signal_keyboard(result.signal.direction, result.signal.id),
        )
