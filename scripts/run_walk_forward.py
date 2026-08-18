from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from app.backtest.walk_forward import run_walk_forward
from app.core.config import get_settings
from app.integrations.market_data.binance_spot import BinanceSpotProvider


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def main():
    parser = argparse.ArgumentParser(description='Walk-forward validation for BTC/USDT Up/Down V1')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--symbol', default='BTCUSDT')
    parser.add_argument('--expiry-minutes', type=int, default=5)
    parser.add_argument('--train-days', type=int, default=14)
    parser.add_argument('--validation-days', type=int, default=7)
    parser.add_argument('--minimum-train-signals', type=int, default=50)
    args = parser.parse_args()

    settings = get_settings()
    provider = BinanceSpotProvider(settings.market_data_rest_base_url, settings.market_data_ws_base_url)
    candles = await provider.fetch_historical_candles(
        args.symbol,
        '1m',
        parse_dt(args.start),
        parse_dt(args.end),
    )

    report = run_walk_forward(
        candles,
        train_days=args.train_days,
        validation_days=args.validation_days,
        expiry_minutes=args.expiry_minutes,
        minimum_train_signals=args.minimum_train_signals,
    )

    print('BC.GAME TRADE — WALK-FORWARD VALIDATION')
    print(f'Folds: {len(report.folds)}')
    print(f'Validation signals: {report.validation_signals}')
    print(f'Validation wins: {report.validation_wins}')
    print(f'Validation losses: {report.validation_losses}')
    print(f'Validation ties: {report.validation_ties}')
    rate = 'n/a' if report.validation_win_rate_ex_ties is None else f'{report.validation_win_rate_ex_ties:.2f}%'
    print(f'Validation win rate excluding ties: {rate}')

    for fold in report.folds:
        train_rate = 'n/a' if fold.train_report.win_rate_ex_ties is None else f'{fold.train_report.win_rate_ex_ties:.2f}%'
        val_rate = 'n/a' if fold.validation_report.win_rate_ex_ties is None else f'{fold.validation_report.win_rate_ex_ties:.2f}%'
        print(
            f'Fold {fold.fold}: score>={fold.selected.min_score}, margin>={fold.selected.min_margin}, '
            f'train={train_rate} ({fold.train_report.signals} signals), '
            f'validation={val_rate} ({fold.validation_report.signals} signals)'
        )

    print('\nUse validation performance, not training performance, to judge whether parameters are stable.')
    print('This remains an external BTC/USDT historical study, not confirmed BC.GAME settlement performance.')


if __name__ == '__main__':
    asyncio.run(main())
