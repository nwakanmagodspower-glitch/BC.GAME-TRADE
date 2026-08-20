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
    if direction in {SignalDirection.UP, SignalDirection.DOWN} and signal_id is not None:
        rows.append([
            InlineKeyboardButton('✅ BCGAME WIN', callback_data=f'calibration:win:{signal_id}'),
            InlineKeyboardButton('❌ BCGAME LOSS', callback_data=f'calibration:loss:{signal_id}'),
        ])
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
        '3️⃣ As soon as you are ready, tap ⚡ Scan Now. The scan starts immediately when the bot receives your tap — there is no 15/14/13/12 estimate anymore.\n\n'
        '🤖 The system will return:\n'
        '🟢 UP  •  🔴 DOWN  •  ⚪ NO TRADE  •  ⚠️ UNAVAILABLE\n\n'
        'If network delay makes the signal arrive too late for that round, skip it and scan the next fresh round.'
    )


def format_signal(signal: Signal) -> str:
    mode = settings.signal_mode.upper()
    paper = '\n\n🧪 PAPER VALIDATION — external market references are not BCGAME settlement truth.' if mode == 'PAPER' else ''

    if signal.direction == SignalDirection.NO_TRADE or signal.status == SignalStatus.NO_TRADE:
        return (
            '⚡ BCGAME BTC/USD — 5s • $1–$50\n\n'
            '⚪ NO TRADE\n\n'
            'This scan did not meet the signal quality gate. Skip it and wait for the next fresh round.' + paper
        )

    icon = '🟢' if signal.direction == SignalDirection.UP else '🔴'
    quality = ((signal.features_snapshot or {}).get('_decision') or {}).get('quality', 'QUALIFIED')

    action = (
        'Recorded for PAPER validation only. Do not place a BCGAME trade.'
        if mode == 'PAPER'
        else '🚀 Open BCGAME now and tap the same direction before the order window closes. If there is not enough time left, skip the round.'
    )
    return (
        '⚡ BCGAME BTC/USD — 5s • $1–$50\n\n'
        f'{icon} SIGNAL: {signal.direction.value}\n\n'
        f'Quality: {quality}\n'
        'Scan timing: captured when you tapped Scan Now\n'
        f'Contract: 5 seconds • ${settings.default_stake_band}\n\n'
        + action + paper
    )
