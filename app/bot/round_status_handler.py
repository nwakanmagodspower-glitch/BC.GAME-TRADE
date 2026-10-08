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

    conn_str = "🟢 Connected & Synchronized" if detrade_observer.connected else "🔴 Disconnected"
    tick = detrade_observer.latest_tick
    price_str = f"${tick['price']:,.2f}" if (tick and isinstance(tick, dict) and 'price' in tick) else None
    tick_age = (
        round(time.monotonic() - tick['received_monotonic'], 2)
        if (tick and isinstance(tick, dict) and 'received_monotonic' in tick)
        else None
    )
    price_line = f"• Synthetic BTC: {price_str} (latency: {tick_age}s)\n" if price_str else ""

    if observation is None:
        error = detrade_observer.last_error or 'Round frame awaiting update.'
        latest_obs = detrade_observer.latest
        last_round_info = ""
        if latest_obs:
            last_round_info = (
                f"• Last Round ID: {latest_obs.round_id or 'unknown'}\n"
                f"• Phase: {latest_obs.phase}\n"
                f"• Status code: {latest_obs.status if latest_obs.status is not None else 'unknown'}\n"
                f"• Feed Age: {latest_obs.data_age_ms} ms\n"
            )

        await update.effective_chat.send_message(
            '🛰 DETRADE TIMER CHECK\n\n'
            f'• Connection: {conn_str}\n'
            f'{price_line}'
            f'{last_round_info}\n'
            f'Status: Round is transitioning or settling on DeTrade. A fresh round opens every few seconds.\n'
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
        f'• Connection: {conn_str}\n'
        f'{price_line}'
        f'• Round ID: {observation.round_id or "unknown"}\n'
        f'• Phase: {observation.phase}\n'
        f'• Status code: {observation.status if observation.status is not None else "unknown"}\n'
        f'• Remaining to Start Rate: {remaining_text}\n'
        f'• 5s evaluation window: {evaluation_text}\n'
        f'• Can safely scan: {"YES" if observation.can_trade else "NO"}\n'
        f'• Feed age: {observation.data_age_ms} ms\n\n'
        f'Signal timing mode: {settings.signal_timing_mode.upper()}\n'
        'Status 1008 and all unknown states are treated as non-tradeable.'
    )
