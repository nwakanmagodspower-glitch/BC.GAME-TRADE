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
            raise SystemExit('External BTC analysis data is not fresh')
        if market_data.get('analysis_symbol') != 'BTCUSDT':
            raise SystemExit(f"Unexpected analysis symbol: {market_data.get('analysis_symbol')}")
        if market_data.get('external_reference_only') is not True:
            raise SystemExit('External market feed is not labelled reference-only')

        webhook = await client.post(base + '/telegram/webhook', json={'update_id': 1})
        if webhook.status_code not in {403, 503}:
            raise SystemExit(f'Webhook accepted an unauthenticated request: {webhook.status_code}')

    if health_data.get('signal_mode') != 'PAPER':
        raise SystemExit('Deployment is not in PAPER mode')
    if health_data.get('signals_enabled_default') is not False:
        raise SystemExit('SIGNALS_ENABLED default is not false')
    if health_data.get('broadcasts_enabled_default') is not False:
        raise SystemExit('BROADCASTS_ENABLED default is not false')
    if health_data.get('topology') != 'web-plus-dedicated-worker':
        raise SystemExit(f"Unexpected topology: {health_data.get('topology')}")

    product = health_data.get('product') or {}
    expected = {
        'game_market': 'BTC/USD',
        'analysis_pair': 'BTCUSDT',
        'product': 'BC_UPDOWN_5S',
        'duration_seconds': 5,
        'stake_band': '1-50',
        'strategy_version': 'BTC_UPDOWN_5S_V1.0',
    }
    for key, value in expected.items():
        if product.get(key) != value:
            raise SystemExit(f'Unexpected product contract {key}: {product.get(key)!r}, expected {value!r}')

    worker = health_data.get('dedicated_worker') or {}
    if not worker.get('seen') or not worker.get('fresh'):
        raise SystemExit(f'Dedicated worker heartbeat is not fresh: {worker}')

    round_sync = health_data.get('round_sync') or {}
    # Initial infrastructure deployment is intentionally fail-closed until the
    # real BC.GAME round provider is integrated.
    if round_sync.get('enabled') is not False:
        raise SystemExit(f'Initial deployment unexpectedly enabled BC.GAME round sync: {round_sync}')
    if round_sync.get('fresh'):
        raise SystemExit('Round sync cannot be fresh while intentionally disabled')

    print('Render five-second safe-deployment smoke tests passed.')
    print(json.dumps({'health': health_data, 'market': market_data}, indent=2, default=str))


if __name__ == '__main__':
    asyncio.run(main())
