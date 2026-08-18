from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import get_settings
from app.integrations.bcgame import bcgame_adapter
from app.models.entities import Signal, SignalDirection, SignalStatus

settings = get_settings()


def build_scan_prompt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🔍 Scan Next Round', callback_data='menu:scan_now')],
        [InlineKeyboardButton('⬅️ Main Menu', callback_data='menu:home')],
    ])


def build_signal_keyboard(direction: SignalDirection) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if (
        settings.signal_mode.upper() == 'LIVE'
        and settings.bcgame_round_sync_enabled
        and direction in {SignalDirection.UP, SignalDirection.DOWN}
        and bcgame_adapter.updown_url
    ):
        rows.append([InlineKeyboardButton('🚀 Open BC.GAME Up/Down', url=bcgame_adapter.updown_url)])
    rows.append([InlineKeyboardButton('🔄 Scan Next Round', callback_data='menu:signal')])
    rows.append([InlineKeyboardButton('⬅️ Main Menu', callback_data='menu:home')])
    return InlineKeyboardMarkup(rows)


def format_scan_context() -> str:
    return (
        '⚡ BTC/USD — BC.GAME 5s UP/DOWN\n\n'
        'Target: the move from BC.GAME Start Rate (first flag) to End Rate (second flag).\n'
        'Contract: 5 seconds\n'
        'V1 stake band: $1–50\n\n'
        'The bot skips weak rounds. Tap below to scan the next synchronized round.'
    )


def format_signal(signal: Signal) -> str:
    mode = settings.signal_mode.upper()
    paper = '\n\n🧪 PAPER VALIDATION — external market references are not BC.GAME settlement truth. Do not place a trade from this result.' if mode == 'PAPER' else ''

    if signal.direction == SignalDirection.NO_TRADE or signal.status == SignalStatus.NO_TRADE:
        return (
            '⚡ BTC/USD — 5s UP/DOWN\n\n'
            '⚪ NO TRADE\n\n'
            'This round did not meet the five-second quality gate. Skipping uncertain rounds is part of the strategy.' + paper
        )

    icon = '🟢' if signal.direction == SignalDirection.UP else '🔴'
    start = signal.entry_at.strftime('%H:%M:%S UTC') if signal.entry_at else 'Pending'
    end = signal.expiry_at.strftime('%H:%M:%S UTC') if signal.expiry_at else 'Pending'
    quality = ((signal.features_snapshot or {}).get('_decision') or {}).get('quality', 'QUALIFIED')
    round_meta = (signal.features_snapshot or {}).get('_bcgame_round') or {}
    round_id = round_meta.get('round_id', 'Synchronized round')
    return (
        '⚡ BTC/USD — BC.GAME 5s UP/DOWN\n\n'
        f'{icon} {signal.direction.value}\n'
        f'Quality: {quality}\n'
        f'Round: {round_id}\n'
        f'🚩 Start Rate time: {start}\n'
        f'🏁 End Rate time: {end}\n'
        f'Stake band: ${settings.default_stake_band}\n\n'
        'Direction refers to the 5-second move after BC.GAME records the Start Rate.' + paper
    )
