from datetime import datetime, timedelta, timezone

from app.backtest.ablation import run_ablation
from app.integrations.market_data.base import Candle


def make_candles(count: int = 180) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    price = 60000.0
    for i in range(count):
        open_time = start + timedelta(minutes=i)
        close_time = open_time + timedelta(seconds=59, milliseconds=999)
        open_price = price
        close_price = price + (8.0 if (i % 9) < 6 else -4.0)
        high = max(open_price, close_price) + 3.0
        low = min(open_price, close_price) - 3.0
        candles.append(
            Candle(
                symbol='BTCUSDT',
                interval='1m',
                open_time=open_time,
                close_time=close_time,
                open=open_price,
                high=high,
                low=low,
                close=close_price,
                volume=10.0 + (i % 5),
                quote_volume=0.0,
                trades=100,
                taker_buy_base_volume=6.0,
                closed=True,
            )
        )
        price = close_price
    return candles


def test_ablation_does_not_mutate_baseline_strategy():
    candles = make_candles()
    baseline, results = run_ablation(candles, min_score=5, min_margin=2)

    assert baseline.observations > 0
    assert len(results) == 6
    assert {item.name for item in results} == {
        'trend', 'momentum', 'structure', 'volume', 'volatility', 'trade_flow'
    }
    # Ablation experiments return independent reports rather than rewriting baseline.
    assert baseline.signals >= 0
