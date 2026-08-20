from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import get_settings
from app.integrations.bcgame import bcgame_adapter
from app.models.entities import Signal, SignalDirection, SignalStatus

settings = get_settings()


def build_scan_prompt_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if bcgame_adapter.updown_url:
        rows.append([InlineKeyboardButton('🚀 Open BCGAME Up/Down', url=bcgame_adapter.updown_url)])
    rows.extend([
        [InlineKeyboardButton('15s', callback_data='menu:scan:15'), InlineKeyboardButton('14s', callback_data='menu:scan:14')],
        [InlineKeyboardButton('13s', callback_data='menu:scan:13'), InlineKeyboardButton('12s', callback_data='menu:scan:12')],
    ])
    return InlineKeyboardMarkup(rows)


def build_signal_keyboard(direction: SignalDirection) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if settings.signal_mode.upper() == 'LIVE' and direction in {SignalDirection.UP, SignalDirection.DOWN} and bcgame_adapter.updown_url:
        rows.append([InlineKeyboardButton('🚀 Open BCGAME Up/Down', url=bcgame_adapter.updown_url)])
    rows.append([InlineKeyboardButton('🔄 Scan Next Round', callback_data='menu:signal')])
    return InlineKeyboardMarkup(rows)


def format_scan_context() -> str:
    return (
        '⚡ BCGAME BTC/USD — 5 SECOND UP/DOWN\n\n'
        '🎯 USE THE CORRECT MARKET\n'
        'Pair: BTC/USD\n'
        'Duration: 5 Seconds\n'
        f'Range: ${settings.default_stake_band}\n\n'
        '⚠️ This bot is designed specifically for the 5s • $1–$50 Up/Down market. Do not use these signals on the other 5-second ranges.\n\n'
        '1️⃣ ENTER YOUR TRADE AMOUNT\n'
        'Open BCGAME Up/Down and enter the amount you want to trade before requesting a signal. Do not tap UP or DOWN yet.\n\n'
        '2️⃣ WATCH THE 15-SECOND COUNTDOWN\n'
        'Wait for a fresh round. When the order window begins, BCGAME counts down from 15 seconds.\n\n'
        '3️⃣ SCAN EARLY\n'
        'When BCGAME shows 15, 14, 13 or 12 seconds, return here and tap the exact matching countdown button immediately.\n\n'
        '🤖 The system will return:\n'
        '🟢 UP  •  🔴 DOWN  •  ⚪ NO TRADE  •  ⚠️ UNAVAILABLE\n\n'
        'If the signal arrives too late for that round, skip it and scan the next fresh round.'
    )


def format_signal(signal: Signal) -> str:
    mode = settings.signal_mode.upper()
    paper = '\n\n🧪 PAPER VALIDATION — external market references are not BCGAME settlement truth.' if mode == 'PAPER' else ''

    if signal.direction == SignalDirection.NO_TRADE or signal.status == SignalStatus.NO_TRADE:
        return (
            '⚡ BCGAME BTC/USD — 5s • $1–$50\n\n'
            '⚪ NO TRADE\n\n'
            'This round did not meet the signal quality gate. Skip it and wait for the next fresh countdown.' + paper
        )

    icon = '🟢' if signal.direction == SignalDirection.UP else '🔴'
    quality = ((signal.features_snapshot or {}).get('_decision') or {}).get('quality', 'QUALIFIED')
    round_meta = (signal.features_snapshot or {}).get('_bcgame_round') or {}
    source = round_meta.get('source', 'UNKNOWN')
    confirmed = round_meta.get('countdown_confirmed_seconds')

    timing_lines = []
    if source == 'MANUAL_SYNC':
        timing_lines.append('⏱ Timing: Manual countdown sync')
        if confirmed is not None:
            timing_lines.append(f'Countdown selected: {confirmed}s')
    timing_text = '\n'.join(timing_lines)
    if timing_text:
        timing_text += '\n'

    action = (
        'Recorded for PAPER validation only. Do not place a BCGAME trade.'
        if mode == 'PAPER'
        else '🚀 Open BCGAME now and tap the same direction before the countdown reaches 0. If there is not enough time left, skip the round.'
    )
    return (
        '⚡ BCGAME BTC/USD — 5s • $1–$50\n\n'
        f'{icon} SIGNAL: {signal.direction.value}\n\n'
        f'Quality: {quality}\n'
        f'{timing_text}'
        f'Contract: 5 seconds • ${settings.default_stake_band}\n\n'
        + action + paper
    )
