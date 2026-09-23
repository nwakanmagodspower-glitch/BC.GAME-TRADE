import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
import pytest

from app.integrations.market_data.base import BookTicker, Candle, DepthLevel, DepthSnapshot, MarketTick
from app.models.entities import SignalDirection
from app.services.market_data import MicrostructureDataCache
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


@pytest.mark.asyncio
async def test_historical_reference_time_freshness():
    cache = MicrostructureDataCache()
    historical_ts = 1600000000.0
    hist_dt = datetime.fromtimestamp(historical_ts, tz=timezone.utc)

    book = BookTicker("BTCUSDT", 90000.0, 2.0, 90000.5, 1.0, hist_dt, "BINANCE_SPOT")
    await cache.add_book_ticker(book)

    # 1. Without reference_time (using real current time), historical event is stale
    stale_snapshot = await cache.get_snapshot("BTCUSDT", max_book_age_seconds=1.0)
    assert stale_snapshot.is_fresh is False

    # 2. With reference_time set to historical timestamp + 0.5s, event is FRESH
    ref_dt = hist_dt + timedelta(seconds=0.5)
    fresh_snapshot = await cache.get_snapshot("BTCUSDT", max_book_age_seconds=1.0, reference_time=ref_dt)
    assert fresh_snapshot.is_fresh is True
    assert fresh_snapshot.book_ticker_age_seconds == pytest.approx(0.5)


def test_dataset_loader_and_validation():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"type": "book_ticker", "event_ts": 1002.0, "bid": 90000, "bid_qty": 1, "ask": 90001, "ask_qty": 1}) + "\n")
        f.write(json.dumps({"type": "book_ticker", "event_ts": 1001.0, "bid": 90000, "bid_qty": 1, "ask": 90001, "ask_qty": 1}) + "\n")
        f.write(json.dumps({"type": "book_ticker", "event_ts": 1001.0, "bid": 90000, "bid_qty": 1, "ask": 90001, "ask_qty": 1}) + "\n")
        f.write("invalid json\n")
        tmp_path = f.name

    try:
        events, stats = load_and_validate_dataset(tmp_path)
        assert len(events) == 3
        assert events[0].event_ts == 1001.0
        assert events[1].event_ts == 1001.0
        assert events[2].event_ts == 1002.0
        assert stats["out_of_order_re_sorted"] == 1
        assert stats["duplicate_timestamps"] == 1
        assert stats["corrupted_lines"] == 1
    finally:
        os.remove(tmp_path)


def test_zero_lookahead_candle_filter():
    now_ts = 100000.0
    candles = [
        create_candle(now_ts - 120),
        create_candle(now_ts - 60),
        create_candle(now_ts),
        create_candle(now_ts + 60),
    ]

    filtered = get_candles_available_at(candles, now_ts)
    assert len(filtered) == 3
    assert all(c.close_time.timestamp() <= now_ts for c in filtered)


@pytest.mark.asyncio
async def test_replay_simulation_paired_same_target():
    base_ts = 1600000000.0
    events = [
        ReplayEvent("book_ticker", base_ts + 0.0, base_ts + 0.0, {"bid": 90000.0, "bid_qty": 5.0, "ask": 90000.5, "ask_qty": 1.0}),
        ReplayEvent("depth", base_ts + 0.1, base_ts + 0.1, {"bids": [[90000.0, 5.0]], "asks": [[90000.5, 1.0]]}),
        ReplayEvent("trade", base_ts + 0.2, base_ts + 0.2, {"price": 90000.5, "qty": 2.0, "is_buyer_maker": False}),
        ReplayEvent("book_ticker", base_ts + 5.5, base_ts + 5.5, {"bid": 90010.0, "bid_qty": 1.0, "ask": 90010.5, "ask_qty": 1.0}),
    ]

    candles = [create_candle(base_ts - i * 60) for i in range(60)]

    paired_obs = await run_replay_simulation(events, candles, eval_interval_seconds=0.5)

    assert len(paired_obs) > 0, "Replay simulation must generate predictions"

    first_obs = paired_obs[0]
    assert first_obs.reference_price == pytest.approx(90000.25)
    assert first_obs.target_5s_price == pytest.approx(90010.25)
    assert first_obs.actual_direction == SignalDirection.UP

    # Confirm both V1 and V2 received predictions evaluated on the exact same target
    assert first_obs.v1_pred is not None
    assert first_obs.v2_pred is not None

    if first_obs.v1_pred.direction in (SignalDirection.UP, SignalDirection.DOWN):
        assert first_obs.v1_pred.is_correct == (first_obs.v1_pred.direction == SignalDirection.UP)

    if first_obs.v2_pred.direction in (SignalDirection.UP, SignalDirection.DOWN):
        assert first_obs.v2_pred.is_correct == (first_obs.v2_pred.direction == SignalDirection.UP)
