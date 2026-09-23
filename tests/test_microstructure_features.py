from datetime import datetime, timezone

import pytest

from app.integrations.market_data.base import BookTicker, Candle, DepthLevel, DepthSnapshot, MarketTick
from app.signals.microstructure.features import (
    build_microstructure_features,
    calculate_microprice,
    calculate_obi_l5,
    calculate_obi_top,
    calculate_tfi,
)


def create_candle(close_price: float) -> Candle:
    now = datetime.now(timezone.utc)
    return Candle(
        symbol="BTCUSDT",
        interval="1m",
        open_time=now,
        close_time=now,
        open=close_price,
        high=close_price + 5.0,
        low=close_price - 5.0,
        close=close_price,
        volume=10.0,
        quote_volume=10.0 * close_price,
        trade_count=100,
        taker_buy_base_volume=5.0,
        taker_buy_quote_volume=5.0 * close_price,
        closed=True,
        provider="BINANCE_SPOT",
    )


def test_calculate_obi_top():
    book = BookTicker(
        symbol="BTCUSDT",
        best_bid_price=90000.0,
        best_bid_qty=3.0,
        best_ask_price=90000.5,
        best_ask_qty=1.0,
        event_time=datetime.now(timezone.utc),
        provider="BINANCE_SPOT",
    )
    # (3.0 - 1.0) / (3.0 + 1.0) = 0.5
    assert calculate_obi_top(book) == pytest.approx(0.5)


def test_calculate_obi_l5():
    now = datetime.now(timezone.utc)
    depth = DepthSnapshot(
        symbol="BTCUSDT",
        bids=(DepthLevel(90000.0, 2.0), DepthLevel(89999.0, 1.0)),
        asks=(DepthLevel(90000.5, 1.0), DepthLevel(90001.0, 1.0)),
        event_time=now,
        provider="BINANCE_SPOT",
    )
    book = BookTicker("BTCUSDT", 90000.0, 2.0, 90000.5, 1.0, now, "BINANCE_SPOT")
    obi_l5 = calculate_obi_l5(depth, book)
    assert obi_l5 > 0.0


def test_calculate_microprice():
    now = datetime.now(timezone.utc)
    book = BookTicker("BTCUSDT", 90000.0, 3.0, 90001.0, 1.0, now, "BINANCE_SPOT")
    # (3.0 * 90001.0 + 1.0 * 90000.0) / 4.0 = 90000.75
    micro = calculate_microprice(book)
    assert micro == pytest.approx(90000.75)


def test_calculate_tfi():
    now = datetime.now(timezone.utc)
    ticks = [
        MarketTick("BTCUSDT", 90000.0, 1.0, now, "BINANCE_SPOT", is_buyer_maker=False),  # Buy
        MarketTick("BTCUSDT", 90000.0, 0.5, now, "BINANCE_SPOT", is_buyer_maker=True),   # Sell
    ]
    tfi, count, total_vol = calculate_tfi(ticks, now, lookback_seconds=5.0)
    assert count == 2
    assert total_vol == pytest.approx(1.5)
    # (1.0 - 0.5) / 1.5 = 0.3333
    assert tfi == pytest.approx(0.333333, abs=1e-4)


def test_build_microstructure_features():
    now = datetime.now(timezone.utc)
    candles = [create_candle(90000.0) for _ in range(60)]
    book = BookTicker("BTCUSDT", 90000.0, 2.0, 90000.5, 1.0, now, "BINANCE_SPOT")
    ticks = [MarketTick("BTCUSDT", 90000.0, 1.0, now, "BINANCE_SPOT", is_buyer_maker=False)]

    features = build_microstructure_features(
        candles=candles,
        latest_book=book,
        book_history=[book],
        depth=None,
        depth_history=(),
        recent_ticks=ticks,
        now=now,
    )

    assert features.mid_price == pytest.approx(90000.25)
    assert features.obi_top == pytest.approx(0.33333, abs=1e-4)
    assert features.spread_bps > 0.0
    assert features.trade_count_1s == 1
