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
            '🛰 DETRADE TIMER CHECK\n\nStatus: disabled\n\nConfigure the private DeTrade token and enable the observer before testing.'
        )
        return

    await update.effective_chat.send_message('🛰 Checking the live DeTrade round…')
    observation = await detrade_observer.probe(timeout_seconds=6.0)
    if observation is None:
        error = detrade_observer.last_error or 'No valid round frame was received.'
        await update.effective_chat.send_message(
            '🛰 DETRADE TIMER CHECK\n\n'
            'Round data: not received\n'
            f'Diagnostic: {error}\n\n'
            'The observer never prints the authentication token or token-bearing WebSocket URL.'
        )
        return

    remaining = observation.remaining_ms
    remaining_text = f'{remaining / 1000:.3f}s' if remaining is not None else 'unknown'
    start_text = str(observation.price_start_time_ms) if observation.price_start_time_ms is not None else 'unknown'
    cutoff_text = str(observation.trade_cutoff_time_ms) if observation.trade_cutoff_time_ms is not None else 'not supplied'

    await update.effective_chat.send_message(
        '🛰 DETRADE ROUND OBSERVER\n\n'
        f'Round ID: {observation.round_id or "unknown"}\n'
        f'Phase: {observation.phase}\n'
        f'Status code: {observation.status if observation.status is not None else "unknown"}\n'
        f'Remaining: {remaining_text}\n'
        f'Can trade: {"YES" if observation.can_trade else "NO"}\n'
        f'Feed age: {observation.data_age_ms} ms\n'
        f'Price start: {start_text}\n'
        f'Trade cutoff: {cutoff_text}\n\n'
        'Observation only — this feed is not controlling live signal timing yet.'
    )
