from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from app.backtest.analytics import (
    breakdown_by_direction,
    breakdown_by_hour_utc,
    breakdown_by_quality,
    breakdown_by_structure,
)
from app.backtest.engine import run_backtest
from app.core.config import get_settings
from app.integrations.market_data.binance_spot import BinanceSpotProvider


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def print_bucket(title, buckets):
    print(f'\n{title}')
    for item in buckets:
        rate = 'n/a' if item.win_rate_ex_ties is None else f'{item.win_rate_ex_ties:.2f}%'
        print(f'- {item.name}: signals={item.signals}, wins={item.wins}, losses={item.losses}, ties={item.ties}, win_rate={rate}')


async def main():
    parser = argparse.ArgumentParser(description='Backtest BTC/USDT BC.GAME Up/Down V1 logic')
    parser.add_argument('--start', required=True, help='ISO timestamp/date, e.g. 2026-06-01T00:00:00Z')
    parser.add_argument('--end', required=True, help='ISO timestamp/date, exclusive end')
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

    report = run_backtest(
        candles,
        expiry_minutes=args.expiry_minutes,
        min_score=args.min_score if args.min_score is not None else settings.signal_min_score,
        min_margin=args.min_margin if args.min_margin is not None else settings.signal_min_margin,
    )

    rate = 'n/a' if report.win_rate_ex_ties is None else f'{report.win_rate_ex_ties:.2f}%'
    print('BC.GAME TRADE — HISTORICAL RESEARCH REPORT')
    print(f'Candles: {len(candles)}')
    print(f'Observations: {report.observations}')
    print(f'Signals: {report.signals}')
    print(f'No Trade: {report.no_trades}')
    print(f'Coverage: {report.coverage_pct:.2f}%')
    print(f'Wins: {report.wins}')
    print(f'Losses: {report.losses}')
    print(f'Ties: {report.ties}')
    print(f'Win rate excluding ties: {rate}')

    print_bucket('BY DIRECTION', breakdown_by_direction(report))
    print_bucket('BY QUALITY', breakdown_by_quality(report))
    print_bucket('BY STRUCTURE', breakdown_by_structure(report))
    print_bucket('BY ENTRY HOUR', breakdown_by_hour_utc(report))

    print('\nIMPORTANT: This is an external BTC/USDT candle backtest, not proof of BC.GAME settlement performance.')


if __name__ == '__main__':
    asyncio.run(main())
