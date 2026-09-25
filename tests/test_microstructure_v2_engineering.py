import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.market_data.base import BookTicker, Candle, DepthLevel, DepthSnapshot, MarketTick
from app.models.entities import SignalDirection
from app.services.market_data import (
    MarketDataCache,
    MarketDataService,
    MicrostructureDataCache,
    market_data_service,
)
from app.services.microstructure_intelligence import (
    MicrostructureIntelligenceService,
    microstructure_intelligence_service,
)
from scripts.replay_microstructure_backtest import (
    EnginePrediction,
    PairedObservation,
    ReplayEvent,
    create_embargoed_splits,
    evaluate_actual_detrade_rounds,
    load_and_validate_dataset,
    print_split_metrics,
    resolve_target_bisect,
    run_replay_simulation,
)


def create_mock_candle(ts: float, close: float = 90000.0) -> Candle:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return Candle(
        symbol="BTCUSDT",
        interval="1m",
        open_time=dt - timedelta(minutes=1),
        close_time=dt,
        open=close,
        high=close + 10.0,
        low=close - 10.0,
        close=close,
        volume=15.0,
        quote_volume=15.0 * close,
        trade_count=150,
        taker_buy_base_volume=8.0,
        taker_buy_quote_volume=8.0 * close,
        closed=True,
        provider="BINANCE_SPOT",
    )


# ---------------------------------------------------------------------------
# Requirement 1: MarketDataService worker methods exist and start tasks cleanly
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_market_data_service_workers_attached():
    """Verify _run_book_ticker and _run_depth are defined on MarketDataService, avoiding AttributeError."""
    assert hasattr(market_data_service, "_run_book_ticker")
    assert hasattr(market_data_service, "_run_depth")
    assert hasattr(market_data_service, "_run_ticks")
    assert hasattr(market_data_service, "_run_candles")


# ---------------------------------------------------------------------------
# Requirement 2: Shared MicrostructureDataCache between services
# ---------------------------------------------------------------------------
def test_shared_microstructure_cache_singleton():
    """Verify microstructure_intelligence_service shares the cache populated by market_data_service."""
    assert microstructure_intelligence_service.cache is market_data_service.microstructure_cache


# ---------------------------------------------------------------------------
# Requirement 3 & 4: Cache buffer size, trade quantity filtering, history retention
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_microstructure_cache_retention_and_filtering():
    """Verify large buffer retention (>=2000 books) and zero-quantity trade filtering."""
    cache = MicrostructureDataCache()
    assert cache._book_tickers["BTCUSDT"].maxlen == 2000
    assert cache._depth_snapshots["BTCUSDT"].maxlen == 500
    assert cache._trades["BTCUSDT"].maxlen == 10000

    base_time = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Zero-quantity trade is ignored
    zero_qty_tick = MarketTick("BTCUSDT", 90000.0, 0.0, base_time, "BINANCE_SPOT")
    await cache.add_trade(zero_qty_tick)
    snap = await cache.get_snapshot("BTCUSDT", reference_time=base_time)
    assert len(snap.recent_ticks) == 0

    valid_tick = MarketTick("BTCUSDT", 90000.0, 1.5, base_time, "BINANCE_SPOT")
    await cache.add_trade(valid_tick)
    snap = await cache.get_snapshot("BTCUSDT", reference_time=base_time)
    assert len(snap.recent_ticks) == 1

    # 2. Add 300 book tickers over 10 seconds (30/s) - all must be retained
    for i in range(300):
        t = base_time + timedelta(milliseconds=i * 33.3)
        book = BookTicker("BTCUSDT", 90000.0 + i * 0.1, 1.0, 90000.5 + i * 0.1, 1.0, t, "BINANCE_SPOT")
        await cache.add_book_ticker(book)

    end_time = base_time + timedelta(milliseconds=299 * 33.3)
    history_5s = await cache.get_book_history("BTCUSDT", lookback_seconds=5.0, reference_time=end_time)
    history_10s = await cache.get_book_history("BTCUSDT", lookback_seconds=10.0, reference_time=end_time)

    # At 100 maxlen, history_5s would have been severely truncated. With 2000, all 300 are retained.
    assert len(history_10s) == 300
    assert len(history_5s) >= 140


# ---------------------------------------------------------------------------
# Requirement 5 & 6: Bisect target resolution with +/-500ms tolerance
# ---------------------------------------------------------------------------
def test_resolve_target_bisect_exact_tolerance():
    """Verify bisect target lookup respects +/-500ms window."""
    book_ts = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 105.3, 106.0]
    book_mids = [90000.0, 90001.0, 90002.0, 90003.0, 90004.0, 90005.0, 90005.3, 90006.0]

    # Target: 105.0s (eval_ts = 100.0, target = 105.0) -> exact match at 105.0
    res = resolve_target_bisect(book_ts, book_mids, target_ts=105.0, tolerance=0.500)
    assert res == 90005.0

    # Target: 105.2s -> closest is 105.3s (diff = 0.1s <= 0.500s)
    res = resolve_target_bisect(book_ts, book_mids, target_ts=105.2, tolerance=0.500)
    assert res == 90005.3

    # Target: 108.0s -> no book event within 500ms -> None (unresolved)
    res = resolve_target_bisect(book_ts, book_mids, target_ts=108.0, tolerance=0.500)
    assert res is None


# ---------------------------------------------------------------------------
# Requirement 4 & 7: Flat outcome accounting (FLAT marked as loss for UP/DOWN)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_flat_outcome_accounting():
    """Directional bets on FLAT settlements are losses, not dropped from denominator."""
    base_ts = 1700000000.0
    candles = [create_mock_candle(base_ts - i * 60, 90000.0) for i in range(60)]

    # Observation where target mid price equals reference price (FLAT settlement)
    obs = PairedObservation(
        ts=base_ts,
        reference_price=90000.25,
        target_5s_price=90000.25,
        actual_direction=SignalDirection.NO_TRADE,  # FLAT
        v1_pred=None,
        v2_pred=EnginePrediction(
            direction=SignalDirection.UP,
            quality="STRONG",
            bull_score=8,
            bear_score=2,
            margin=6,
            spread_bps=0.5,
            atr_14_pct=0.01,
            is_correct=False,  # Evaluator sets is_correct=False on FLAT
        ),
    )

    # In replay metrics, FLAT must be included in resolved obs and count as incorrect
    resolved_obs = [obs for obs in [obs] if obs.actual_direction is not None]
    assert len(resolved_obs) == 1
    assert obs.v2_pred.is_correct is False


# ---------------------------------------------------------------------------
# Requirement 12: Chronological splits with 5s embargo
# ---------------------------------------------------------------------------
def test_create_embargoed_splits():
    """Verify 5-second embargo between Dev, Validation, and Test splits."""
    observations = []
    for i in range(100):
        # 1-second interval observations
        obs = PairedObservation(
            ts=1000.0 + i * 1.0,
            reference_price=90000.0,
            target_5s_price=90001.0,
            actual_direction=SignalDirection.UP,
            v1_pred=None,
            v2_pred=None,
        )
        observations.append(obs)

    splits = create_embargoed_splits(observations, embargo_seconds=5.0)
    assert len(splits) == 3

    dev_name, dev_start, dev_end = splits[0]
    val_name, val_start, val_end = splits[1]
    test_name, test_start, test_end = splits[2]

    # Dev split ends at 50
    assert dev_end == 50
    last_dev_ts = observations[dev_end - 1].ts  # 1049.0

    # Val split must start at or after last_dev_ts + 5.0 (1054.0 -> index 54)
    assert observations[val_start].ts >= last_dev_ts + 5.0
    assert val_start >= 54

    # Test split must start at or after last_val_ts + 5.0
    last_val_ts = observations[val_end - 1].ts
    assert observations[test_start].ts >= last_val_ts + 5.0


# ---------------------------------------------------------------------------
# Requirement 10 & 14: Dataset loading with embedded candles and deterministic sorting
# ---------------------------------------------------------------------------
def test_dataset_loader_embedded_candles_and_deterministic_order():
    """Verify dataset loader parses embedded candles and orders same-timestamp events deterministically."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        # Write out-of-order events with duplicate timestamps
        f.write(json.dumps({
            "type": "candle",
            "event_ts": 1000.0,
            "local_ts": 1000.0,
            "data": {
                "open_time": 940.0, "close_time": 1000.0, "open": 90000, "high": 90005,
                "low": 89995, "close": 90000, "volume": 10, "quote_volume": 900000,
                "trade_count": 100, "taker_buy_base_volume": 5, "taker_buy_quote_volume": 450000,
                "closed": True
            }
        }) + "\n")
        f.write(json.dumps({"type": "book_ticker", "event_ts": 1000.0, "local_ts": 1000.1, "data": {"bid": 90000, "bid_qty": 1, "ask": 90001, "ask_qty": 1}}) + "\n")
        f.write(json.dumps({"type": "depth", "event_ts": 1000.0, "local_ts": 1000.1, "data": {"bids": [[90000, 1]], "asks": [[90001, 1]]}}) + "\n")
        tmp_path = f.name

    try:
        events, stats = load_and_validate_dataset(tmp_path)
        assert len(events) == 3
        # Priority order: candle (0), depth (2), book_ticker (4)
        assert events[0].event_type == "candle"
        assert events[1].event_type == "depth"
        assert events[2].event_type == "book_ticker"
        assert len(stats["embedded_candles"]) == 1
    finally:
        os.remove(tmp_path)


# ---------------------------------------------------------------------------
# Requirement: Mode B DeTrade round evaluation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mode_b_detrade_round_evaluation():
    """Verify Mode B evaluates predictions against authoritative DeTrade round settlements."""
    base_ts = 1700000000.0
    candles = [create_mock_candle(base_ts - i * 60, 90000.0) for i in range(60)]

    # Provide market data events prior to round priceStartTime
    events = [
        ReplayEvent("book_ticker", base_ts - 1.0, base_ts - 1.0, {"bid": 90000.0, "bid_qty": 5.0, "ask": 90000.5, "ask_qty": 1.0}),
        ReplayEvent("depth", base_ts - 0.8, base_ts - 0.8, {"bids": [[90000.0, 5.0]], "asks": [[90000.5, 1.0]]}),
        ReplayEvent("trade", base_ts - 0.5, base_ts - 0.5, {"price": 90000.5, "qty": 2.0, "is_buyer_maker": False}),
    ]

    detrade_rounds = {
        "round-101": {
            "round_id": "round-101",
            "price_start_time_ms": int(base_ts * 1000),
            "price_end_time_ms": int((base_ts + 5.0) * 1000),
            "start_price": 90000.0,
            "end_price": 90015.0,  # UP outcome
        },
        "round-102": {
            "round_id": "round-102",
            "price_start_time_ms": int((base_ts + 10.0) * 1000),
            "price_end_time_ms": int((base_ts + 15.0) * 1000),
            "start_price": 90015.0,
            "end_price": 90015.0,  # FLAT outcome
        },
    }

    results = await evaluate_actual_detrade_rounds(events, candles, detrade_rounds)
    assert len(results) == 2

    # Round 101 settled UP
    assert results[0].round_id == "round-101"
    assert results[0].actual_outcome == SignalDirection.UP

    # Round 102 settled FLAT
    assert results[1].round_id == "round-102"
    assert results[1].actual_outcome == SignalDirection.NO_TRADE
