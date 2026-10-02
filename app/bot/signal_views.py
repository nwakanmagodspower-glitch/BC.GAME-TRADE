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


def _room_label() -> str:
    room = getattr(settings, 'detrade_stake_room', None) or getattr(settings, 'default_stake_band', '1-50')
    if not room.startswith('$'):
        room = f'${room}'
    return room


def format_scan_context() -> str:
    room = _room_label()
    return (
        '⚡ BCGAME BTC/USD — 5 SECOND UP/DOWN\n\n'
        '🎯 CORRECT MARKET\n'
        'Pair: BTC/USD\n'
        'Duration: 5 Seconds\n'
        f'Room: {room}\n\n'
        '🎯 STAKE GUIDANCE:\n'
        '• Strong Setup: Stake High\n'
        '• Standard Setup: Stake Low\n'
        '• Flat / Choppy / Late: Skip Round\n\n'
        f'1️⃣ Open BCGAME Up/Down and select {room}. Do not choose UP or DOWN yet.\n\n'
        '2️⃣ Wait for a fresh round to begin (~15–20s countdown).\n\n'
        '3️⃣ Tap ⚡ Scan Market immediately. The bot checks timing, synthetic momentum, and exhaustion risk before returning a decision.\n\n'
        '🟢 UP — qualified upward setup (exhaustion filtered)\n'
        '🔴 DOWN — qualified downward setup\n'
        '⚪ NO TRADE — no qualified setup (flat chop, late window, or counter-trend)\n'
        '⚠️ UNAVAILABLE — timing or market data is not safe enough\n\n'
        'If under 8 seconds remain, the bot advises skipping to prevent latency slippage.'
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
    room = _room_label()
    reason_str = signal.status_reason or decision.get('reason', '')

    if signal.direction == SignalDirection.NO_TRADE or signal.status == SignalStatus.NO_TRADE:
        bull = decision.get('bull_score', 0)
        bear = decision.get('bear_score', 0)
        quality = decision.get('quality', '')
        lead_range = (signal.features_snapshot or {}).get('lead_range_dollars')
        if lead_range is None:
            lead_range = (signal.features_snapshot or {}).get('bar_5s_range')

        if 'entry window too short' in reason_str.lower() or 'too short' in reason_str.lower():
            return (
                f'⚡ BCGAME BTC/USD — 5s • {room}\n\n'
                '⚪ NO TRADE — Late Entry Window\n\n'
                '⏱️ Window: Less than 8.0s remaining before round starts\n'
                '🎯 Stake: 🛡️ Skip Round (Wait for fresh round)\n\n'
                '💡 Why skip? With under 8 seconds remaining, there is not enough time to switch apps and execute cleanly on BC.GAME without latency slippage.\n'
                'Wait for the next round (~15–20s countdown) and scan as soon as it begins.'
                + paper
            )

        if 'trend conflict' in reason_str.lower() or 'macro' in reason_str.lower():
            return (
                f'⚡ BCGAME BTC/USD — 5s • {room}\n\n'
                '⚪ NO TRADE — Trend Conflict\n\n'
                '📊 Alignment: Short-term tick contradicts macro 1-minute trend\n'
                '🎯 Stake: 🛡️ Skip Round (Wait for trend alignment)\n\n'
                '💡 Why skip? The 5-second impulse contradicts the broader market trend. Counter-trend 5s trades carry low win rates.\n'
                'Preserve capital and wait for momentum that aligns with the macro trend.'
                + paper
            )

        if 'exhaustion' in reason_str.lower() or 'overextended' in reason_str.lower():
            return (
                f'⚡ BCGAME BTC/USD — 5s • {room}\n\n'
                '⚪ NO TRADE — Parabolic Exhaustion\n\n'
                f'📊 Warning: Pre-start impulse is overextended\n'
                '🎯 Stake: 🛡️ Skip Round\n\n'
                '💡 Why skip? BTC surged aggressively during the countdown. Buying at the peak risks an immediate 5-second mean-reversion loss.\n'
                'Skipping preserves your balance until a stable continuation setup appears.'
                + paper
            )

        min_range = getattr(settings, 'detrade_min_5s_range_dollars', settings.signal_min_lead_range_dollars)
        if quality == 'LOW_SPEED' or 'too narrow' in reason_str.lower() or (isinstance(lead_range, (int, float)) and 0.0 < lead_range < min_range):
            range_str = f'${float(lead_range):.2f}' if isinstance(lead_range, (int, float)) else 'Low'
            return (
                f'⚡ BCGAME BTC/USD — 5s • {room}\n\n'
                '⚪ NO TRADE — Low Market Speed\n\n'
                f'📊 BTC Speed: {range_str} range (Flat Chop)\n'
                '🎯 Stake: 🛡️ Skip Round\n\n'
                '💡 Why skip? Under BCGAME rules, ties (End <= Start) award the round to DOWN. In flat chop, UP has negative expected value.\n'
                'Skipping preserves your balance until clean momentum returns.\n\n'
                'Wait for a fresh round with active movement before scanning again.'
                + paper
            )

        score_line = f'\n📊 Momentum Scan: Bull {bull}/10 • Bear {bear}/10 (Flat)\n' if (bull or bear) else ''
        return (
            f'⚡ BCGAME BTC/USD — 5s • {room}\n\n'
            '⚪ NO TRADE\n'
            + score_line +
            '\n🎯 Stake: 🛡️ Skip Round\n'
            'No qualified setup right now (momentum is neutral, choppy, or edge is insufficient).\n'
            'Skip this round rather than forcing an entry, and wait for a clear directional setup.'
            + paper
        )

    icon = '🟢' if signal.direction == SignalDirection.UP else '🔴'
    quality = decision.get('quality', 'QUALIFIED')
    conf_tag = _format_confidence_tag(decision)
    entry_window = _entry_window_text(signal)
    lead_range = (signal.features_snapshot or {}).get('lead_range_dollars')
    if lead_range is None:
        lead_range = (signal.features_snapshot or {}).get('bar_5s_range')
    speed_line = f'📊 Momentum Range: ${float(lead_range):.2f} expansion\n' if isinstance(lead_range, (int, float)) and lead_range > 0 else ''
    tie_note = '💡 Tie rule: Qualified expansion confirmed.\n' if signal.direction == SignalDirection.UP else '💡 Tie advantage: DOWN wins on flat ties.\n'
    stake_rec = decision.get('stake_recommendation')
    if not stake_rec or 'allocation' in stake_rec.lower() or 'setup' in stake_rec.lower():
        bull = decision.get('bull_score', 0)
        bear = decision.get('bear_score', 0)
        peak = max(bull, bear)
        margin = decision.get('margin', abs(bull - bear))
        if peak >= 8 or (peak >= 6 and margin >= 4):
            stake_rec = '🔥 Stake High'
        else:
            stake_rec = '⚡ Stake Low'
    stake_line = f'🎯 Stake: {stake_rec}\n'
    action = (
        'Recorded for PAPER validation only.'
        if mode == 'PAPER'
        else f'🚀 Direction: {signal.direction.value}. Use it only if the BCGAME entry window is still open.'
    )
    return (
        f'⚡ BCGAME BTC/USD — 5s • {room}\n\n'
        f'{icon} {signal.direction.value} SIGNAL\n\n'
        f'🔥 Strength: {quality} • {conf_tag}\n'
        + speed_line
        + entry_window
        + tie_note
        + stake_line
        + '\n'
        + action
        + paper
    )
