from telegram import Update
from telegram.ext import ContextTypes

from app.core.config import get_settings
from app.integrations.detrade_observer import detrade_observer

settings = get_settings()


def _owner_private_chat(update: Update) -> bool:
    return bool(
        settings.owner_telegram_id
        and update.effective_user
        and update.effective_user.id == settings.owner_telegram_id
        and update.effective_chat
        and update.effective_chat.type == 'private'
        and update.effective_chat.id == settings.owner_telegram_id
    )


async def round_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner_private_chat(update):
        if update.effective_chat:
            await update.effective_chat.send_message('This command is available only in the owner private chat.')
        return

    if not settings.detrade_ws_enabled:
        await update.effective_chat.send_message(
            '🛰 DETRADE TIMER CHECK\n\n'
            'Status: not enabled on this deployment\n'
            f'Signal timing mode: {settings.signal_timing_mode.upper()}\n\n'
            'The normal signal system can still use its manual Scan Now fallback in HYBRID_SYNC mode.'
        )
        return

    await update.effective_chat.send_message('🛰 Checking the live BCGAME/DeTrade round…')
    observation = await detrade_observer.probe(timeout_seconds=settings.detrade_probe_timeout_seconds)
    if observation is None:
        error = detrade_observer.last_error or 'No valid round frame was received.'
        await update.effective_chat.send_message(
            '🛰 DETRADE TIMER CHECK\n\n'
            'Round data: not received\n'
            f'Diagnostic: {error}\n\n'
            'No token, cookie, access code, or token-bearing URL is printed by this command.'
        )
        return

    remaining = observation.remaining_ms
    remaining_text = f'{remaining / 1000:.3f}s' if remaining is not None else 'unknown'
    evaluation_ms = None
    if observation.price_start_time_ms is not None and observation.price_end_time_ms is not None:
        evaluation_ms = observation.price_end_time_ms - observation.price_start_time_ms
    evaluation_text = f'{evaluation_ms / 1000:.3f}s' if evaluation_ms is not None else 'unknown'

    await update.effective_chat.send_message(
        '🛰 BCGAME ROUND TIMER\n\n'
        f'Round ID: {observation.round_id or "unknown"}\n'
        f'Phase: {observation.phase}\n'
        f'Status code: {observation.status if observation.status is not None else "unknown"}\n'
        f'Remaining to Start Rate: {remaining_text}\n'
        f'5s evaluation window: {evaluation_text}\n'
        f'Can safely scan: {"YES" if observation.can_trade else "NO"}\n'
        f'Feed age: {observation.data_age_ms} ms\n\n'
        f'Signal timing mode: {settings.signal_timing_mode.upper()}\n'
        'Status 1008 and all unknown states are treated as non-tradeable.'
    )
