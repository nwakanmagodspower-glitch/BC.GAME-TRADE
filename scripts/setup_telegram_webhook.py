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

    base = args.base_url.rstrip('/') + '/'
    if not base.startswith('https://'):
        raise SystemExit('--base-url must use HTTPS')
    webhook_url = urljoin(base, 'telegram/webhook')

    bot = Bot(settings.telegram_bot_token)
    ok = await bot.set_webhook(
        url=webhook_url,
        secret_token=settings.telegram_webhook_secret,
        allowed_updates=['message', 'callback_query'],
        drop_pending_updates=False,
    )
    if not ok:
        raise SystemExit('Telegram rejected webhook configuration')

    info = await bot.get_webhook_info()
    if info.url != webhook_url:
        raise SystemExit(f'Webhook verification mismatch: {info.url!r}')

    print('Telegram webhook configured and verified.')
    print(f'URL: {webhook_url}')
    print(f'Pending updates: {info.pending_update_count}')


if __name__ == '__main__':
    asyncio.run(main())
