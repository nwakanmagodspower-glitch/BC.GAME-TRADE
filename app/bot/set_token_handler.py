"""Owner-only /set_token command handler.

Usage:
    /set_token <paste anything>

The handler accepts:
  - Raw JWT:             eyJhbGciOi...
  - WebSocket URL:       wss://websocket.detrade.com/ws?token=eyJ...
  - cURL command:        curl ... -H 'Authorization: Bearer eyJ...'
  - Any text block from DevTools Network panel

After validating the token, it:
  1. Persists it to the database (survives Render restarts).
  2. Stops the current DeTradeObserver socket.
  3. Restarts the observer — it will immediately connect with the new credential.
  4. Waits up to 3 seconds for a live round observation to confirm connectivity.
  5. Returns a detailed status report.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.integrations.bcgame_rounds import bcgame_round_service
from app.integrations.detrade_observer import detrade_observer
from app.integrations.detrade_token_provider import detrade_token_provider
from app.services.detrade_token_service import DeTradeTokenService

settings = get_settings()


def _is_owner(update: Update) -> bool:
    return bool(
        update.effective_user
        and update.effective_chat
        and update.effective_chat.type == 'private'
        and settings.owner_telegram_id
        and update.effective_user.id == settings.owner_telegram_id
        and update.effective_chat.id == settings.owner_telegram_id
    )


async def set_token_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only: update the DeTrade WebSocket token at runtime."""
    if not _is_owner(update) or not update.message or not update.effective_user:
        return

    raw_input = ' '.join(context.args or []).strip()
    if not raw_input:
        await update.message.reply_text(
            '🔑 DETRADE TOKEN UPDATE\n\n'
            'Usage: /set_token <paste token or URL>\n\n'
            'You can paste:\n'
            '  • The raw JWT (starts with eyJ…)\n'
            '  • A full WebSocket URL\n'
            '  • A cURL command from DevTools\n'
            '  • Any text block containing the token\n\n'
            'The bot will extract and validate the token automatically.'
        )
        return

    # --- Validate and persist ---
    with SessionLocal() as db:
        result = DeTradeTokenService(db).update(raw_input, update.effective_user.id)

    if not result.ok:
        await update.message.reply_text(
            f'❌ TOKEN REJECTED\n\n{result.error}'
        )
        return

    # --- Hot-reload the observer ---
    await update.message.reply_text('⏳ Token accepted — reconnecting to DeTrade…')

    # Reset any invalidated state on the provider so it will try again
    if hasattr(detrade_token_provider, '_invalidated'):
        detrade_token_provider._invalidated = False

    await detrade_observer.stop()
    await detrade_observer.start()

    # Wait briefly for a live observation (up to 3 seconds)
    observation = await detrade_observer.probe(timeout_seconds=3.0)

    # --- Build status report ---
    expiry_str = (
        result.expires_at.strftime('%H:%M UTC on %a %d %b')
        if result.expires_at else 'unknown'
    )
    remaining_str = (
        f'{int(result.remaining_hours or 0)}h {result.remaining_minutes or 0}m'
        if result.remaining_hours is not None else 'unknown'
    )

    if observation and observation.fresh:
        connection_status = '🟢 Connected & Synchronized'
        round_line = (
            f'• Current Round ID: {observation.round_id or "–"}\n'
            f'• Phase: {observation.phase}\n'
            f'• Can Trade: {"YES" if observation.can_trade else "NO"}\n'
            f'• Feed Age: {observation.data_age_ms} ms\n'
        )
    else:
        connection_status = '🟡 Token accepted — observer connecting (may take a few seconds)'
        err = detrade_observer.last_error or 'No round frame received yet'
        round_line = f'• Observer status: {err}\n'

    timing_status = bcgame_round_service.status()
    timing_line = '🟢 Ready' if timing_status.fresh else '🔴 Not ready'

    report = (
        '✅ DETRADE TOKEN ACTIVATED\n\n'
        f'• Connection: {connection_status}\n'
        f'• Expires: {expiry_str}\n'
        f'• Remaining: {remaining_str}\n'
        f'• Signal Timing Layer: {timing_line}\n'
        f'• Signal Mode: {settings.signal_mode.upper()}\n'
        f'• Timing Mode: {settings.signal_timing_mode.upper()}\n\n'
        f'{round_line}'
        '\n'
        '⚠️ The token value is never echoed back here.\n'
        'Run /round_status to check the live timer at any time.'
    )
    await update.message.reply_text(report)
