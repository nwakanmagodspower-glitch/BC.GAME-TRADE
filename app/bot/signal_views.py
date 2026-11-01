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
        '🎯 SIGNAL GUIDE:\n'
        '• 🔥 STAKE HIGH — Highest Confidence Setup (Best Win Rate)\n'
        '• Standard Signal — Strong Market Movement (Normal Trade)\n'
        '• 🛡️ Skip Round — Flat Market or Sideways Movement\n\n'
        f'1️⃣ Open BCGAME Up/Down and select {room}. Do not choose UP or DOWN yet.\n\n'
        '2️⃣ Watch the round timer on BC.GAME.\n\n'
        '3️⃣ Best Timing: Tap ⚡ Scan Market when the countdown is around 8s to 12s remaining. This gives you a comfortable 5–7 seconds to switch to BC.Game and place your trade with zero rush.\n\n'
        '🟢 UP — Clear upward move\n'
        '🔴 DOWN — Clear downward move\n'
        '⚪ NO TRADE — Flat market or sideways move (skip round)\n'
        '⚠️ UNAVAILABLE — Round already started or updating'
    )


def _entry_window_text(signal: Signal) -> str:
    data = signal.features_snapshot or {}
    round_meta = data.get('_bcgame_round') or {}
    lines = []
    if round_meta.get('source') == 'DETRADE_SYNC':
        remaining = round_meta.get('remaining_seconds_at_scan')
        if isinstance(remaining, (int, float)):
            lines.append(f'⏱️ Entry window: ~{float(remaining):.1f}s\n')

    projected = data.get('projected_expiry_drift_usd')
    if isinstance(projected, (int, float)) and abs(projected) >= 0.15:
        sign = '+' if projected > 0 else ''
        lines.append(f'🎯 Expected Target: {sign}${float(projected):.2f}\n')
    return ''.join(lines)


REGIME_HUMAN_NAMES = {
    'LAMINAR_THRUST': 'Strong Trend',
    'MOMENTUM_EXPANSION': 'Fast Momentum',
    'EXHAUSTION_TOP': 'Reversal Down',
    'EXHAUSTION_BOTTOM': 'Reversal Up',
    'BOUNDED_REBOUND': 'Support Bounce',
    'MODERATE_LEAN': 'Steady Move',
    'MICRO_CHOP': 'Flat Market',
}


def _human_regime_label(raw: str) -> str:
    if not raw:
        return 'Confirmed Move'
    upper = raw.upper()
    return REGIME_HUMAN_NAMES.get(upper, upper.replace('_', ' ').title())


def _format_confidence_tag(decision: dict) -> str:
    ai_pred = decision.get('ai_prediction')
    if ai_pred and isinstance(ai_pred, dict):
        conf = ai_pred.get('confidence_pct')
        regime = ai_pred.get('ai_regime', '')
        human_regime = _human_regime_label(regime)
        if conf:
            return f'{conf}% ({human_regime})'

    bull = decision.get('bull_score', 0)
    bear = decision.get('bear_score', 0)
    peak = max(bull, bear)
    if peak >= 7:
        return '94% (Very High Confidence)'
    elif peak >= 5:
        return '85% (High Confidence)'
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

        if 'already started' in reason_str.lower():
            return (
                f'⚡ BCGAME BTC/USD — 5s • {room}\n\n'
                '⚪ NO TRADE — Round Already Started\n\n'
                '⏱️ Window: The round countdown has already reached 0:00\n'
                '🎯 Stake: 🛡️ Skip Round\n\n'
                '💡 Wait for the next round countdown and tap Scan to get your signal.'
                + paper
            )

        if 'trend conflict' in reason_str.lower() or 'macro' in reason_str.lower():
            return (
                f'⚡ BCGAME BTC/USD — 5s • {room}\n\n'
                '⚪ NO TRADE — Trend Conflict\n\n'
                '📊 Alignment: Short-term tick contradicts macro 1-minute trend\n'
                '🎯 Stake: 🛡️ Skip Round (Wait for trend alignment)\n\n'
                'Preserve capital and wait for momentum that aligns with the macro trend.'
                + paper
            )

        min_range = getattr(settings, 'detrade_min_5s_range_dollars', settings.signal_min_lead_range_dollars)
        if quality == 'LOW_SPEED' or 'too narrow' in reason_str.lower() or 'neutral consolidation' in reason_str.lower() or (isinstance(lead_range, (int, float)) and 0.0 < lead_range < min_range):
            range_str = f'${float(lead_range):.2f}' if isinstance(lead_range, (int, float)) else f'<${min_range:.2f}'
            return (
                f'⚡ BCGAME BTC/USD — 5s • {room}\n\n'
                '⚪ NO TRADE — Low Market Speed\n'
                '🛡️ Chop Defense: Capital Preserved\n\n'
                f'📊 BTC Speed: {range_str} range (Flat Chop)\n'
                '🎯 Stake: 🛡️ Skip Round\n\n'
                '💡 Market momentum is too low for a high-probability trade.\n'
                'Skipping preserves your balance until clean momentum returns.\n\n'
                'Wait for a fresh round with active movement before scanning again.'
                + paper
            )

        return (
            f'⚡ BCGAME BTC/USD — 5s • {room}\n\n'
            '⚪ NO TRADE\n\n'
            '🎯 Stake: 🛡️ Skip Round\n'
            'No qualified setup right now (momentum is neutral, choppy, or edge is insufficient).\n'
            'Skip this round rather than forcing an entry, and wait for a clear directional setup.'
            + paper
        )

    icon = '🟢' if signal.direction == SignalDirection.UP else '🔴'
    stake_rec = decision.get('stake_recommendation') or ''
    if not stake_rec or 'allocation' in stake_rec.lower() or 'setup' in stake_rec.lower():
        bull = decision.get('bull_score', 0)
        bear = decision.get('bear_score', 0)
        peak = max(bull, bear)
        margin = decision.get('margin', abs(bull - bear))
        if peak >= 8 or (peak >= 6 and margin >= 4 and (signal.features_snapshot or {}).get('bar_5s_return', 0) >= 0.80):
            stake_rec = '🔥 Stake High'
        else:
            stake_rec = ''

    quality = decision.get('quality', 'CONFIRMED')
    if quality == 'VALID':
        quality = 'CONFIRMED'
    conf_tag = _format_confidence_tag(decision)
    entry_window = _entry_window_text(signal)
    lead_range = (signal.features_snapshot or {}).get('lead_range_dollars')
    if lead_range is None:
        lead_range = (signal.features_snapshot or {}).get('bar_5s_range')
    speed_line = f'📊 Momentum Range: ${float(lead_range):.2f} expansion\n' if isinstance(lead_range, (int, float)) and lead_range > 0 else ''

    ai_pred = decision.get('ai_prediction')
    ai_line = ''
    if ai_pred and isinstance(ai_pred, dict):
        prob = ai_pred.get('up_probability' if signal.direction == SignalDirection.UP else 'down_probability')
        regime = ai_pred.get('ai_regime', '')
        human_regime = _human_regime_label(regime)
        if prob:
            ai_line = f'🤖 AI Confidence: {int(round(float(prob) * 100))}% ({human_regime})\n'

    if 'stake high' in stake_rec.lower():
        stake_line = '🎯 VIP Stake: 🔥 STAKE HIGH (Best Win Rate)\n'
    else:
        stake_line = ''

    action = (
        'Recorded for PAPER validation only.'
        if mode == 'PAPER'
        else f'🚀 Action: Select {signal.direction.value} on BC.GAME now!'
    )
    return (
        f'⚡ BCGAME BTC/USD — 5s • {room}\n\n'
        f'{icon} {signal.direction.value} SIGNAL\n\n'
        + ai_line
        + f'🔥 Strength: {quality} • {conf_tag}\n'
        + speed_line
        + entry_window
        + stake_line
        + '\n'
        + action
        + paper
    )
