from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from app.backtest.stability import run_feature_stability
from app.core.config import get_settings
from app.integrations.market_data.binance_spot import BinanceSpotProvider


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def main():
    parser = argparse.ArgumentParser(description='Cross-window BTC/USDT feature stability research')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--window-days', type=int, default=14)
    parser.add_argument('--symbol', default='BTCUSDT')
    parser.add_argument('--expiry-minutes', type=int, default=5)
    args = parser.parse_args()

    start = parse_dt(args.start)
    end = parse_dt(args.end)
    if end <= start:
        raise SystemExit('--end must be after --start')
    if args.window_days < 1:
        raise SystemExit('--window-days must be >= 1')

    settings = get_settings()
    provider = BinanceSpotProvider(settings.market_data_rest_base_url, settings.market_data_ws_base_url)
    windows = []
    cursor = start
    while cursor < end:
        window_end = min(cursor + timedelta(days=args.window_days), end)
        candles = await provider.fetch_historical_candles(args.symbol, '1m', cursor, window_end)
        if candles:
            windows.append(candles)
        cursor = window_end

    report = run_feature_stability(
        windows,
        expiry_minutes=args.expiry_minutes,
        min_score=settings.signal_min_score,
        min_margin=settings.signal_min_margin,
    )

    print('BC.GAME TRADE — CROSS-WINDOW FEATURE STABILITY')
    print(f'Windows analysed: {len(report.windows)}')
    for feature in report.features:
        delta = 'n/a' if feature.mean_win_rate_delta_pct is None else f'{feature.mean_win_rate_delta_pct:+.2f}pp'
        print(
            f'- {feature.family}: {feature.stable_classification}; '
            f'helpful={feature.helpful_windows}, harmful_candidate={feature.harmful_candidate_windows}, '
            f'inconclusive={feature.inconclusive_windows}, mean_delta={delta}'
        )

    print('\nResearch only: stable evidence does not alter BTC_UPDOWN_V1.0 or authorize deployment.')


if __name__ == '__main__':
    asyncio.run(main())
