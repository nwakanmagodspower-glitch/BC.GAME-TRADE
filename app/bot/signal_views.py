from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import get_settings
from app.integrations.bcgame import bcgame_adapter
from app.models.entities import Signal, SignalDirection, SignalStatus

settings = get_settings()


def build_scan_prompt_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton('15s', callback_data='menu:scan:15'), InlineKeyboardButton('14s', callback_data='menu:scan:14')],
        [InlineKeyboardButton('13s', callback_data='menu:scan:13'), InlineKeyboardButton('12s', callback_data='menu:scan:12')],
        [InlineKeyboardButton('⬅️ Main Menu', callback_data='menu:home')],
    ]
    return InlineKeyboardMarkup(rows)


def build_signal_keyboard(direction: SignalDirection) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if settings.signal_mode.upper() == 'LIVE' and direction in {SignalDirection.UP, SignalDirection.DOWN} and bcgame_adapter.updown_url:
        rows.append([InlineKeyboardButton('🚀 Open BC.GAME Up/Down', url=bcgame_adapter.updown_url)])
    rows.append([InlineKeyboardButton('🔄 Next Round', callback_data='menu:signal')])
    rows.append([InlineKeyboardButton('⬅️ Main Menu', callback_data='menu:home')])
    return InlineKeyboardMarkup(rows)


def format_scan_context() -> str:
    return (
        '⚡ BTC/USD — BC.GAME 5s UP/DOWN\n\n'
        'Before scanning:\n'
        '1) Open BC.GAME Up/Down.\n'
        '2) Select BTC/USD and 5s.\n'
        '3) Enter your stake first.\n'
        '4) Wait for a fresh 15-second countdown.\n\n'
        'When BC.GAME shows 15, 14, 13, or 12 seconds, tap the matching button below immediately.\n\n'
        'The bot returns UP, DOWN, or NO TRADE for that current round.'
    )


def format_signal(signal: Signal) -> str:
    mode = settings.signal_mode.upper()
    paper = '\n\n🧪 PAPER VALIDATION — external market references are not BC.GAME settlement truth.' if mode == 'PAPER' else ''

    if signal.direction == SignalDirection.NO_TRADE or signal.status == SignalStatus.NO_TRADE:
        return (
            '⚡ BTC/USD — 5s UP/DOWN\n\n'
            '⚪ NO TRADE\n\n'
            'The current round did not meet the five-second quality gate. Skip it and wait for the next fresh countdown.' + paper
        )

    icon = '🟢' if signal.direction == SignalDirection.UP else '🔴'
    quality = ((signal.features_snapshot or {}).get('_decision') or {}).get('quality', 'QUALIFIED')
    round_meta = (signal.features_snapshot or {}).get('_bcgame_round') or {}
    source = round_meta.get('source', 'UNKNOWN')
    start = signal.entry_at.strftime('%H:%M:%S UTC') if signal.entry_at else 'Estimated'
    end = signal.expiry_at.strftime('%H:%M:%S UTC') if signal.expiry_at else 'Estimated'

    manual_note = ''
    if source == 'MANUAL_SYNC':
        manual_note = (
            '\n\n⏱ Manual timer sync\n'
            'Use this direction only for the round whose countdown you just confirmed. '
            'If BC.GAME is already below about 7 seconds when this arrives, skip the round.'
        )

    action = (
        'Recorded for PAPER validation only. Do not place a BC.GAME trade.'
        if mode == 'PAPER'
        else 'Tap the same direction on BC.GAME before its countdown reaches 0.'
    )
    return (
        '⚡ BTC/USD — BC.GAME 5s UP/DOWN\n\n'
        f'{icon} {signal.direction.value}\n'
        f'Quality: {quality}\n'
        f'Contract: 5s • ${settings.default_stake_band}\n'
        f'Estimated Start: {start}\n'
        f'Estimated End: {end}\n\n'
        + action
        + manual_note + paper
    )
