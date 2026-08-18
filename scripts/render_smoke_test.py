from __future__ import annotations

import argparse
import asyncio
import json

import httpx


async def main() -> None:
    parser = argparse.ArgumentParser(description='Smoke-test BC.GAME TRADE Render deployment.')
    parser.add_argument('--base-url', required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    if not base.startswith('https://'):
        raise SystemExit('--base-url must use HTTPS')

    async with httpx.AsyncClient(timeout=15.0) as client:
        health = await client.get(base + '/health')
        if health.status_code != 200:
            raise SystemExit(f'/health failed: {health.status_code} {health.text}')
        health_data = health.json()

        ready = await client.get(base + '/ready')
        if ready.status_code != 200:
            raise SystemExit(f'/ready failed: {ready.status_code} {ready.text}')

        market = await client.get(base + '/market/status')
        if market.status_code != 200:
            raise SystemExit(f'/market/status failed: {market.status_code} {market.text}')
        market_data = market.json()
        if not market_data.get('fresh'):
            raise SystemExit('Market data is not fresh')

        # Security check: webhook without Telegram secret must not be accepted.
        webhook = await client.post(base + '/telegram/webhook', json={'update_id': 1})
        if webhook.status_code not in {403, 503}:
            raise SystemExit(f'Webhook accepted an unauthenticated request: {webhook.status_code}')

    if health_data.get('signal_mode') != 'PAPER':
        raise SystemExit('Deployment is not in PAPER mode')
    if health_data.get('signals_enabled_default') is not False:
        raise SystemExit('SIGNALS_ENABLED default is not false')

    print('Render smoke tests passed.')
    print(json.dumps({'health': health_data, 'market': market_data}, indent=2, default=str))


if __name__ == '__main__':
    asyncio.run(main())
