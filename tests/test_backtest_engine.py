from datetime import datetime, timedelta, timezone

from app.backtest.engine import run_backtest
from app.integrations.market_data.base import Candle


def make_candles(count: int, start_price: float = 100.0):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    price = start_price
    for i in range(count):
        open_time = start + timedelta(minutes=i)
        close_time = open_time + timedelta(minutes=1) - timedelta(milliseconds=1)
        open_price = price
        close_price = price + 0.2
        candles.append(
            Candle(
                symbol='BTCUSDT',
                interval='1m',
                open_time=open_time,
                close_time=close_time,
                open=open_price,
                high=close_price + 0.1,
                low=open_price - 0.1,
                close=close_price,
                volume=10 + i * 0.1,
                quote_volume=1000,
                trade_count=100,
                taker_buy_base_volume=7.0,
                taker_buy_quote_volume=700,
                closed=True,
                provider='TEST',
            )
        )
        price = close_price
    return candles


def test_backtest_uses_next_candle_as_entry_and_five_minutes_later_as_expiry():
    candles = make_candles(100)
    report = run_backtest(candles, expiry_minutes=5, min_score=1, min_margin=1, warmup_candles=60)
    assert report.observations > 0
    assert report.signals > 0
    first = report.trades[0]
    assert first.entry_time == candles[60].open_time
    assert first.expiry_time == candles[65].open_time
    assert first.entry_price == candles[60].open
    assert first.expiry_price == candles[65].open


def test_backtest_counts_no_trade_without_creating_trade_record():
    candles = make_candles(100)
    report = run_backtest(candles, expiry_minutes=5, min_score=999, min_margin=999, warmup_candles=60)
    assert report.signals == 0
    assert report.no_trades == report.observations
    assert report.trades == []
