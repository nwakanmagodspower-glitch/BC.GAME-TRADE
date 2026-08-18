from datetime import datetime, timedelta, timezone

from app.backtest.walk_forward import run_walk_forward
from app.integrations.market_data.base import Candle


def make_candles(days: int = 35) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    price = 100.0
    for i in range(days * 24 * 60):
        open_time = start + timedelta(minutes=i)
        # Deterministic alternating trend blocks to exercise multiple folds.
        direction = 0.03 if (i // 180) % 2 == 0 else -0.025
        close = price + direction
        high = max(price, close) + 0.01
        low = min(price, close) - 0.01
        candles.append(
            Candle(
                symbol='BTCUSDT',
                interval='1m',
                open_time=open_time,
                close_time=open_time + timedelta(minutes=1) - timedelta(milliseconds=1),
                open=price,
                high=high,
                low=low,
                close=close,
                volume=10.0,
                quote_volume=1000.0,
                trade_count=100,
                taker_buy_base_volume=6.0 if direction > 0 else 4.0,
                taker_buy_quote_volume=600.0 if direction > 0 else 400.0,
                closed=True,
                provider='TEST',
            )
        )
        price = close
    return candles


def test_walk_forward_produces_separate_validation_folds():
    report = run_walk_forward(
        make_candles(),
        train_days=14,
        validation_days=7,
        expiry_minutes=5,
        min_scores=(5, 6),
        min_margins=(2, 3),
        minimum_train_signals=10,
    )
    assert len(report.folds) >= 2
    for fold in report.folds:
        assert fold.train_end == fold.validation_start
        assert fold.validation_start < fold.validation_end
        assert fold.selected.min_score in {5, 6}
        assert fold.selected.min_margin in {2, 3}
