from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import get_settings
from app.integrations.bcgame import bcgame_adapter
from app.models.entities import Signal, SignalDirection, SignalStatus

settings = get_settings()


def build_scan_prompt_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if bcgame_adapter.updown_url:
        rows.append([InlineKeyboardButton('🚀 Open BCGAME Up/Down', url=bcgame_adapter.updown_url)])
    rows.append([InlineKeyboardButton('⚡ Scan Now', callback_data='menu:scan_now')])
    return InlineKeyboardMarkup(rows)


def build_signal_keyboard(direction: SignalDirection, signal_id: int | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if settings.signal_mode.upper() == 'LIVE' and direction in {SignalDirection.UP, SignalDirection.DOWN} and bcgame_adapter.updown_url:
        rows.append([InlineKeyboardButton('🚀 Open BCGAME Up/Down', url=bcgame_adapter.updown_url)])
    rows.append([InlineKeyboardButton('🔄 Scan Next Round', callback_data='menu:scan_now')])
    return InlineKeyboardMarkup(rows)


def format_scan_context() -> str:
    return (
        '⚡ BCGAME BTC/USD — 5 SECOND UP/DOWN\n\n'
        '🎯 CORRECT MARKET\n'
        'Pair: BTC/USD\n'
        'Duration: 5 Seconds\n'
        f'Range: ${settings.default_stake_band}\n\n'
        '1️⃣ Open BCGAME Up/Down and enter the amount you want to trade. Do not tap UP or DOWN yet.\n\n'
        '2️⃣ Wait for a fresh round to begin.\n\n'
        '3️⃣ Tap ⚡ Scan Now. When synchronized BCGAME timing is available, the bot checks the active round before scanning.\n\n'
        '🤖 Possible responses:\n'
        '🟢 UP  •  🔴 DOWN  •  ⚪ NO TRADE  •  ⚠️ UNAVAILABLE\n\n'
        'If the round is already too close to cutoff, skip it and scan the next fresh round.'
    )


def _timing_text(signal: Signal) -> str:
    data = signal.features_snapshot or {}
    round_meta = data.get('_bcgame_round') or {}
    trigger = data.get('_scan_trigger') or {}
    if round_meta.get('source') == 'DETRADE_SYNC':
        remaining = round_meta.get('remaining_seconds_at_scan')
        remaining_text = f'~{float(remaining):.1f}s' if isinstance(remaining, (int, float)) else 'available'
        round_id = round_meta.get('round_id') or 'unknown'
        return (
            f'Round: #{round_id}\n'
            f'BCGAME timer at scan: {remaining_text}\n'
            'Timing: synchronized\n'
        )
    if trigger.get('mode') == 'MANUAL_FALLBACK':
        return 'Timing: manual fallback — synchronized round feed was unavailable\n'
    return 'Timing: Scan Now trigger\n'


def format_signal(signal: Signal) -> str:
    mode = settings.signal_mode.upper()
    paper = '\n\n🧪 PAPER VALIDATION — external market references are not BCGAME settlement truth.' if mode == 'PAPER' else ''
    timing = _timing_text(signal)

    if signal.direction == SignalDirection.NO_TRADE or signal.status == SignalStatus.NO_TRADE:
        return (
            '⚡ BCGAME BTC/USD — 5s • $1–$50\n\n'
            '⚪ NO TRADE\n\n'
            + timing + '\n'
            'This scan did not meet the signal quality gate. Skip it and wait for the next fresh round.' + paper
        )

    icon = '🟢' if signal.direction == SignalDirection.UP else '🔴'
    quality = ((signal.features_snapshot or {}).get('_decision') or {}).get('quality', 'QUALIFIED')
    action = (
        'Recorded for PAPER validation only.'
        if mode == 'PAPER'
        else '🚀 Open BCGAME now and tap the same direction before the order window closes. If there is not enough time left, skip the round.'
    )
    return (
        '⚡ BCGAME BTC/USD — 5s • $1–$50\n\n'
        f'{icon} SIGNAL: {signal.direction.value}\n\n'
        f'Quality: {quality}\n'
        + timing
        + f'Contract: 5 seconds • ${settings.default_stake_band}\n\n'
        + action + paper
    )
