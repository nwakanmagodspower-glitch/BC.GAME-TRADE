from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import get_settings
from app.integrations.bcgame import bcgame_adapter
from app.models.entities import Signal, SignalDirection, SignalStatus

settings = get_settings()


def build_scan_prompt_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if bcgame_adapter.updown_url:
        rows.append([InlineKeyboardButton('🚀 Open BCGAME Up/Down', url=bcgame_adapter.updown_url)])
    rows.append([InlineKeyboardButton('⚡ Scan Market', callback_data='menu:scan_now')])
    return InlineKeyboardMarkup(rows)


def build_signal_keyboard(direction: SignalDirection, signal_id: int | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if settings.signal_mode.upper() == 'LIVE' and direction in {SignalDirection.UP, SignalDirection.DOWN} and bcgame_adapter.updown_url:
        rows.append([InlineKeyboardButton('🚀 Open BCGAME Up/Down', url=bcgame_adapter.updown_url)])
    rows.append([InlineKeyboardButton('⚡ Scan Market', callback_data='menu:scan_now')])
    return InlineKeyboardMarkup(rows)


def format_scan_context() -> str:
    return (
        '⚡ BCGAME BTC/USD — 5 SECOND UP/DOWN\n\n'
        '🎯 CORRECT MARKET\n'
        'Pair: BTC/USD\n'
        'Duration: 5 Seconds\n'
        f'Range: ${settings.default_stake_band}\n\n'
        '1️⃣ Open BCGAME Up/Down and set your amount. Do not choose UP or DOWN yet.\n\n'
        '2️⃣ Wait for a fresh round to begin.\n\n'
        '3️⃣ Tap ⚡ Scan Market. The bot checks timing and market quality before returning a decision.\n\n'
        '🟢 UP — qualified upward setup\n'
        '🔴 DOWN — qualified downward setup\n'
        '⚪ NO TRADE — no qualified setup\n'
        '⚠️ UNAVAILABLE — timing or market data is not safe enough\n\n'
        'If the round is already late, skip it rather than forcing an entry.'
    )


def _entry_window_text(signal: Signal) -> str:
    data = signal.features_snapshot or {}
    round_meta = data.get('_bcgame_round') or {}
    if round_meta.get('source') == 'DETRADE_SYNC':
        remaining = round_meta.get('remaining_seconds_at_scan')
        if isinstance(remaining, (int, float)):
            return f'⏱️ Entry window: ~{float(remaining):.1f}s\n'
    return ''


def format_signal(signal: Signal) -> str:
    mode = settings.signal_mode.upper()
    paper = '\n\n🧪 PAPER VALIDATION' if mode == 'PAPER' else ''

    if signal.direction == SignalDirection.NO_TRADE or signal.status == SignalStatus.NO_TRADE:
        return (
            '⚡ BCGAME BTC/USD — 5s • $1–$50\n\n'
            '⚪ NO TRADE\n\n'
            'No qualified setup right now. Skip this round rather than forcing an entry.'
            + paper
        )

    icon = '🟢' if signal.direction == SignalDirection.UP else '🔴'
    quality = ((signal.features_snapshot or {}).get('_decision') or {}).get('quality', 'QUALIFIED')
    entry_window = _entry_window_text(signal)
    action = (
        'Recorded for PAPER validation only.'
        if mode == 'PAPER'
        else f'🚀 Direction: {signal.direction.value}. Use it only if the BCGAME entry window is still open.'
    )
    return (
        '⚡ BCGAME BTC/USD — 5s • $1–$50\n\n'
        f'{icon} {signal.direction.value} SIGNAL\n\n'
        f'🔥 Strength: {quality}\n'
        + entry_window
        + '\n'
        + action
        + paper
    )
