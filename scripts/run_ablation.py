from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from app.backtest.ablation import run_ablation
from app.core.config import get_settings
from app.integrations.market_data.binance_spot import BinanceSpotProvider


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def main():
    parser = argparse.ArgumentParser(description='Feature ablation research for BTC/USDT Up/Down V1')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--symbol', default='BTCUSDT')
    parser.add_argument('--expiry-minutes', type=int, default=5)
    parser.add_argument('--min-score', type=int, default=None)
    parser.add_argument('--min-margin', type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    provider = BinanceSpotProvider(settings.market_data_rest_base_url, settings.market_data_ws_base_url)
    candles = await provider.fetch_historical_candles(
        args.symbol,
        '1m',
        parse_dt(args.start),
        parse_dt(args.end),
    )

    baseline, results = run_ablation(
        candles,
        expiry_minutes=args.expiry_minutes,
        min_score=args.min_score if args.min_score is not None else settings.signal_min_score,
        min_margin=args.min_margin if args.min_margin is not None else settings.signal_min_margin,
    )

    baseline_rate = 'n/a' if baseline.win_rate_ex_ties is None else f'{baseline.win_rate_ex_ties:.2f}%'
    print('BC.GAME TRADE — FEATURE ABLATION RESEARCH')
    print(f'Baseline signals: {baseline.signals}')
    print(f'Baseline win rate: {baseline_rate}')
    print(f'Baseline coverage: {baseline.coverage_pct:.2f}%')

    for result in results:
        rate = 'n/a' if result.report.win_rate_ex_ties is None else f'{result.report.win_rate_ex_ties:.2f}%'
        delta = 'n/a' if result.win_rate_delta_pct is None else f'{result.win_rate_delta_pct:+.2f}pp'
        print(
            f'- remove {result.name}: signals={result.report.signals}, '
            f'win_rate={rate}, rate_delta={delta}, '
            f'coverage_delta={result.coverage_delta_pct:+.2f}pp'
        )

    print('\nInterpretation: a single ablation window is evidence only, not permission to change production weights.')
    print('Any material strategy change must receive a new version and pass unseen validation plus PAPER forward testing.')


if __name__ == '__main__':
    asyncio.run(main())
