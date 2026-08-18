from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import get_settings
from app.models.entities import SignalDirection

settings = get_settings()


def build_signal_keyboard(direction: SignalDirection) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if direction in {SignalDirection.UP, SignalDirection.DOWN} and settings.bcgame_updown_url:
        rows.append([
            InlineKeyboardButton('🚀 Open BC.GAME Up/Down', url=settings.bcgame_updown_url)
        ])

    rows.append([
        InlineKeyboardButton('🔍 Scan Again', callback_data='menu:signal')
    ])

    return InlineKeyboardMarkup(rows)
