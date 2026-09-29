from __future__ import annotations

import argparse
import asyncio
from urllib.parse import urljoin

from telegram import Bot

from app.core.config import get_settings
from app.core.startup import validate_settings


async def main() -> None:
    parser = argparse.ArgumentParser(description='Configure the production Telegram webhook safely.')
    parser.add_argument('--base-url', required=True, help='Render web service base URL, e.g. https://service.onrender.com')
    args = parser.parse_args()

    settings = get_settings()
    check = validate_settings(settings)
    if not check.ok:
        raise SystemExit('Configuration invalid: ' + '; '.join(check.errors))

    try:
        base = args.base_url.rstrip('/') + '/'
        if not base.startswith('https://'):
            print('WARNING: --base-url must use HTTPS; skipping webhook configuration')
            return
        webhook_url = urljoin(base, 'telegram/webhook')

        if not settings.telegram_bot_token:
            print('WARNING: TELEGRAM_BOT_TOKEN not configured; skipping webhook configuration')
            return

        bot = Bot(settings.telegram_bot_token)
        ok = await bot.set_webhook(
            url=webhook_url,
            secret_token=settings.telegram_webhook_secret,
            allowed_updates=['message', 'callback_query'],
            drop_pending_updates=False,
        )
        if not ok:
            print('WARNING: Telegram rejected webhook configuration')
            return

        info = await bot.get_webhook_info()
        print('Telegram webhook configured and verified.')
        print(f'URL: {webhook_url}')
        print(f'Pending updates: {info.pending_update_count}')
    except Exception as exc:
        print(f'WARNING: Could not complete Telegram webhook setup: {exc}. Starting server anyway.')


if __name__ == '__main__':
    asyncio.run(main())
