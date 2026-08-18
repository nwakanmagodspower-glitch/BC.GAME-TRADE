from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import get_settings
from app.integrations.bcgame import bcgame_adapter
from app.models.entities import Signal, SignalDirection, SignalStatus

settings = get_settings()


def build_scan_prompt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🔍 Scan Now', callback_data='menu:scan_now')],
        [InlineKeyboardButton('⬅️ Main Menu', callback_data='menu:home')],
    ])


def build_signal_keyboard(direction: SignalDirection) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if (
        settings.signal_mode.upper() == 'LIVE'
        and direction in {SignalDirection.UP, SignalDirection.DOWN}
        and bcgame_adapter.updown_url
    ):
        rows.append([InlineKeyboardButton('🚀 Open BC.GAME Up/Down', url=bcgame_adapter.updown_url)])

    rows.append([InlineKeyboardButton('🔍 Scan Again', callback_data='menu:signal')])
    rows.append([InlineKeyboardButton('⬅️ Main Menu', callback_data='menu:home')])
    return InlineKeyboardMarkup(rows)


def format_signal(signal: Signal) -> str:
    mode = settings.signal_mode.upper()
    mode_note = '\n\n🧪 PAPER VALIDATION — do not place a trade from this result.' if mode == 'PAPER' else ''

    if signal.direction == SignalDirection.NO_TRADE or signal.status == SignalStatus.NO_TRADE:
        return (
            'BTC/USDT — UP/DOWN\n\n'
            '⚪ NO TRADE\n\n'
            'The current setup did not meet the strategy quality gate. '
            'Waiting is part of the system.' + mode_note
        )

    icon = '🟢' if signal.direction == SignalDirection.UP else '🔴'
    entry = signal.entry_at.strftime('%H:%M:%S UTC') if signal.entry_at else 'Pending'
    expiry = signal.expiry_at.strftime('%H:%M:%S UTC') if signal.expiry_at else 'Pending'
    quality = ((signal.features_snapshot or {}).get('_decision') or {}).get('quality', 'QUALIFIED')
    return (
        'BTC/USDT — BC.GAME UP/DOWN\n\n'
        f'{icon} Direction: {signal.direction.value}\n'
        f'Quality: {quality}\n\n'
        f'⏱ Planned entry: {entry}\n'
        f'⌛ Planned expiry: {expiry}\n\n'
        'Wait for the planned entry time. If market conditions invalidate the setup, '
        'the backend can cancel it before activation.' + mode_note
    )
