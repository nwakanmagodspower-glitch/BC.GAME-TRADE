from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.bot.admin_handlers import (
    admin_command, admin_ops_callback, broadcast_callback, broadcast_command,
    restore_command, suspend_command,
)
from app.bot.handlers import (
    admin_review_callback, menu_callback, onboarding_callback, photo_input, start, text_input,
)
from app.bot.round_status_handler import round_status_command
from app.bot.preflight_handler import preflight_command
from app.core.config import get_settings

settings = get_settings()


def build_telegram_application() -> Application | None:
    if not settings.telegram_bot_token:
        return None

    application = Application.builder().token(settings.telegram_bot_token).updater(None).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('admin', admin_command))
    application.add_handler(CommandHandler('broadcast', broadcast_command))
    application.add_handler(CommandHandler('suspend', suspend_command))
    application.add_handler(CommandHandler('restore', restore_command))
    application.add_handler(CommandHandler('round_status', round_status_command))
    application.add_handler(CommandHandler('preflight', preflight_command))
    application.add_handler(CallbackQueryHandler(broadcast_callback, pattern=r'^adminops:broadcast_(confirm|cancel):'))
    application.add_handler(CallbackQueryHandler(admin_ops_callback, pattern=r'^adminops:'))
    application.add_handler(CallbackQueryHandler(admin_review_callback, pattern=r'^admin:'))
    application.add_handler(CallbackQueryHandler(onboarding_callback, pattern=r'^onboard:'))
    application.add_handler(CallbackQueryHandler(menu_callback, pattern=r'^menu:'))
    application.add_handler(MessageHandler(filters.PHOTO, photo_input))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input))
    return application
