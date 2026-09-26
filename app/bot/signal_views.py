from __future__ import annotations

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


def _format_confidence_tag(decision: dict) -> str:
    bull = decision.get('bull_score', 0)
    bear = decision.get('bear_score', 0)
    peak = max(bull, bear)
    if peak >= 7:
        return '94% (High Conviction)'
    elif peak >= 5:
        return '85% (Triple Confluence)'
    return '75% (Confirmed)'


def format_signal(signal: Signal) -> str:
    mode = settings.signal_mode.upper()
    paper = '\n\n🧪 PAPER VALIDATION' if mode == 'PAPER' else ''
    decision = (signal.features_snapshot or {}).get('_decision') or {}

    if signal.direction == SignalDirection.NO_TRADE or signal.status == SignalStatus.NO_TRADE:
        bull = decision.get('bull_score', 0)
        bear = decision.get('bear_score', 0)
        quality = decision.get('quality', '')
        lead_range = (signal.features_snapshot or {}).get('lead_range_dollars')

        if quality == 'LOW_SPEED' or (isinstance(lead_range, (int, float)) and 0.0 < lead_range < settings.signal_min_lead_range_dollars):
            range_str = f'${float(lead_range):.2f}' if isinstance(lead_range, (int, float)) else 'Low'
            return (
                '⚡ BCGAME BTC/USD — 5s • $1–$50\n\n'
                '⚪ NO TRADE — Low Market Speed\n\n'
                f'📊 BTC Speed: {range_str} range (Flat Chop)\n'
                '💡 Why skip? BCGAME 5-second rounds result in tie-losses when BTC does not move. '
                'Skipping preserves your balance until clean momentum returns.\n\n'
                'Wait for a fresh round with active movement before scanning again.'
                + paper
            )

        score_line = f'\n📊 Momentum Scan: Bull {bull}/10 • Bear {bear}/10 (Flat)\n' if (bull or bear) else ''
        return (
            '⚡ BCGAME BTC/USD — 5s • $1–$50\n\n'
            '⚪ NO TRADE\n'
            + score_line +
            '\nNo qualified setup right now (momentum is neutral or choppy).\n'
            'Skip this round rather than forcing an entry, and wait for a clear directional setup.'
            + paper
        )

    icon = '🟢' if signal.direction == SignalDirection.UP else '🔴'
    quality = decision.get('quality', 'QUALIFIED')
    conf_tag = _format_confidence_tag(decision)
    entry_window = _entry_window_text(signal)
    lead_range = (signal.features_snapshot or {}).get('lead_range_dollars')
    speed_line = f'📊 Momentum Range: ${float(lead_range):.2f} expansion\n' if isinstance(lead_range, (int, float)) and lead_range > 0 else ''
    action = (
        'Recorded for PAPER validation only.'
        if mode == 'PAPER'
        else f'🚀 Direction: {signal.direction.value}. Use it only if the BCGAME entry window is still open.'
    )
    return (
        '⚡ BCGAME BTC/USD — 5s • $1–$50\n\n'
        f'{icon} {signal.direction.value} SIGNAL\n\n'
        f'🔥 Strength: {quality} • {conf_tag}\n'
        + speed_line
        + entry_window
        + '\n'
        + action
        + paper
    )
