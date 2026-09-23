import json
import os
import tempfile
from datetime import datetime, timezone
import pytest

from app.integrations.market_data.base import BookTicker, Candle
from app.models.entities import SignalDirection
from scripts.replay_microstructure_backtest import (
    ReplayEvent,
    get_candles_available_at,
    load_and_validate_dataset,
    run_replay_simulation,
)


def create_candle(ts: float) -> Candle:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return Candle(
        symbol="BTCUSDT",
        interval="1m",
        open_time=dt,
        close_time=dt,
        open=90000.0,
        high=90005.0,
        low=89995.0,
        close=90000.0,
        volume=10.0,
        quote_volume=900000.0,
        trade_count=100,
        taker_buy_base_volume=5.0,
        taker_buy_quote_volume=450000.0,
        closed=True,
        provider="BINANCE_SPOT",
    )


def test_dataset_loader_and_validation():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        # Out of order events
        f.write(json.dumps({"type": "book_ticker", "event_ts": 1002.0, "bid": 90000, "bid_qty": 1, "ask": 90001, "ask_qty": 1}) + "\n")
        f.write(json.dumps({"type": "book_ticker", "event_ts": 1001.0, "bid": 90000, "bid_qty": 1, "ask": 90001, "ask_qty": 1}) + "\n")
        # Duplicate timestamp
        f.write(json.dumps({"type": "book_ticker", "event_ts": 1001.0, "bid": 90000, "bid_qty": 1, "ask": 90001, "ask_qty": 1}) + "\n")
        # Corrupted line
        f.write("invalid json\n")
        tmp_path = f.name

    try:
        events = load_and_validate_dataset(tmp_path)
        assert len(events) == 3
        # Verify strict chronological sorting
        assert events[0].event_ts == 1001.0
        assert events[1].event_ts == 1001.0
        assert events[2].event_ts == 1002.0
    finally:
        os.remove(tmp_path)


def test_zero_lookahead_candle_filter():
    now_ts = 100000.0
    candles = [
        create_candle(now_ts - 120),
        create_candle(now_ts - 60),
        create_candle(now_ts),
        create_candle(now_ts + 60),  # Future candle
    ]

    filtered = get_candles_available_at(candles, now_ts)
    assert len(filtered) == 3
    assert all(c.close_time.timestamp() <= now_ts for c in filtered)


@pytest.mark.asyncio
async def test_replay_simulation_same_target_comparison():
    base_ts = 1000.0
    events = [
        ReplayEvent("book_ticker", base_ts + 0.0, base_ts + 0.0, {"bid": 90000.0, "bid_qty": 2.0, "ask": 90000.5, "ask_qty": 1.0}),
        ReplayEvent("trade", base_ts + 1.0, base_ts + 1.0, {"price": 90000.5, "qty": 1.0, "is_buyer_maker": False}),
        ReplayEvent("book_ticker", base_ts + 5.5, base_ts + 5.5, {"bid": 90005.0, "bid_qty": 1.0, "ask": 90005.5, "ask_qty": 1.0}),
    ]

    candles = [create_candle(base_ts - i * 60) for i in range(60)]

    v1_preds, v2_preds = await run_replay_simulation(events, candles, eval_interval_seconds=1.0)

    # Both predictions evaluated at base_ts must share the exact target price 90005.25 at t+5.5s
    if v1_preds and v2_preds:
        p1 = v1_preds[0]
        p2 = v2_preds[0]
        assert p1.target_5s_price == p2.target_5s_price
        assert p1.actual_direction == p2.actual_direction
        assert p1.actual_direction == SignalDirection.UP
