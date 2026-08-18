from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.bot.handlers import (
    admin_review_callback,
    menu_callback,
    onboarding_callback,
    photo_input,
    start,
    text_input,
)
from app.core.config import get_settings

settings = get_settings()


def build_telegram_application() -> Application | None:
    if not settings.telegram_bot_token:
        return None

    application = Application.builder().token(settings.telegram_bot_token).updater(None).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(admin_review_callback, pattern=r'^admin:'))
    application.add_handler(CallbackQueryHandler(onboarding_callback, pattern=r'^onboard:'))
    application.add_handler(CallbackQueryHandler(menu_callback, pattern=r'^menu:'))
    application.add_handler(MessageHandler(filters.PHOTO, photo_input))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input))
    return application
