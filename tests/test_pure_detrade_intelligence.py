import pytest
from datetime import datetime, timezone, timedelta

from app.integrations.market_data.base import BookTicker
from app.integrations.market_data.five_second_bar import FiveSecondBar
from app.models.entities import SignalDirection
from app.signals.microstructure.features import build_microstructure_features
from app.signals.microstructure.scoring import score_microstructure_features
from app.signals.microstructure.decision import decide_microstructure

def test_pure_detrade_regime_context_without_binance_candles():
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker(
        symbol="BTCUSDT",
        best_bid_price=84500.0,
        best_bid_qty=1.0,
        best_ask_price=84500.0,
        best_ask_qty=1.0,
        event_time=now,
        provider="DETRADE_SYNTHETIC",
    )
    bars_5s = [
        FiveSecondBar(
            bucket_ts=ts - 5,
            open=84490.0,
            high=84502.0,
            low=84489.0,
            close=84500.0,
            volume=5.0,
            quote_volume=5.0 * 84500.0,
            trades_count=10,
            taker_buy_volume=3.5,
            taker_sell_volume=1.5,
            closed=True,
        )
    ]
    bar_metrics = {
        'ema_fast_9': 84495.0,
        'ema_slow_21': 84490.0,
        'rsi_14': 62.0,
        'momentum_3bar_usd': 3.5,
    }

    # Pass candles=None, is_synthetic=True
    features = build_microstructure_features(
        candles=None,
        latest_book=book,
        now=now,
        bars_5s=bars_5s,
        bar_metrics_5s=bar_metrics,
        is_synthetic=True,
    )

    # Regime context must be derived from 5s bar metrics, not Binance candles
    assert features.ema_fast == 84495.0
    assert features.ema_slow == 84490.0
    assert features.rsi_14 == 62.0
    assert features.bar_5s_return == 10.0
    assert features.bar_5s_range == 13.0

def test_pure_detrade_chop_filtering():
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker("BTCUSDT", 84500.0, 1.0, 84500.0, 1.0, now, "DETRADE_SYNTHETIC")
    
    # 5s bar with narrow range ($0.40 < $1.00 min range)
    bars_5s = [
        FiveSecondBar(
            bucket_ts=ts - 5,
            open=84500.0, high=84500.4, low=84500.0, close=84500.2,
            volume=2.0, quote_volume=2.0 * 84500.0, trades_count=4,
            taker_buy_volume=1.0, taker_sell_volume=1.0, closed=True,
        )
    ]
    features = build_microstructure_features(
        latest_book=book, now=now, bars_5s=bars_5s, is_synthetic=True,
    )
    score = score_microstructure_features(features, is_synthetic=True)
    decision = decide_microstructure(
        score=score,
        features=features,
        min_5s_range=1.00,
        is_synthetic=True,
    )

    # Must filter chop and recommend Skip Round
    assert decision.direction == SignalDirection.NO_TRADE
    assert "narrow" in decision.reason.lower() or "range" in decision.reason.lower()
    assert decision.stake_recommendation == "🛡️ Skip Round"

def test_pure_detrade_strong_expansion_gives_stake_high():
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker("BTCUSDT", 84510.0, 1.0, 84510.0, 1.0, now, "DETRADE_SYNTHETIC")
    
    # Strong expansion bar (range $3.00, return $2.50)
    bars_5s = [
        FiveSecondBar(
            bucket_ts=ts - 5,
            open=84507.5, high=84510.5, low=84507.5, close=84510.0,
            volume=5.0, quote_volume=5.0 * 84510.0, trades_count=10,
            taker_buy_volume=4.0, taker_sell_volume=1.0, closed=True,
        )
    ]
    bar_metrics = {
        'ema_fast_9': 84508.0,
        'ema_slow_21': 84502.0,
        'rsi_14': 60.0,
        'momentum_3bar_usd': 2.5,
    }
    features = build_microstructure_features(
        latest_book=book, now=now, bars_5s=bars_5s, bar_metrics_5s=bar_metrics, is_synthetic=True,
    )
    score = score_microstructure_features(features, is_synthetic=True)
    decision = decide_microstructure(
        score=score,
        features=features,
        min_score=6,
        min_margin=3,
        min_5s_range=1.00,
        is_synthetic=True,
        up_min_margin=4,
    )

    assert decision.direction == SignalDirection.UP
    assert decision.stake_recommendation == "🔥 Stake High"


@pytest.mark.asyncio
async def test_pure_detrade_end_to_end_decoupling():
    import time
    from app.integrations.detrade_observer import detrade_observer
    from app.services.microstructure_intelligence import microstructure_intelligence_service

    now_utc = datetime.now(timezone.utc)
    ts = int(now_utc.timestamp())

    # Pre-populate detrade_observer with pure synthetic ticks and closed bars
    detrade_observer.latest_tick = {
        'price': 84650.25,
        'timestamp_ms': ts * 1000,
        'symbol': 'BTCUSDT',
        'change': 1.50,
        'received_monotonic': time.monotonic(),
        'received_at': now_utc,
        'source': 'WS_STREAM',
    }
    detrade_observer.bar_aggregator.clear()
    detrade_observer.bar_aggregator.add_synthetic_tick(price=84640.0, timestamp_ms=(ts - 10) * 1000)
    detrade_observer.bar_aggregator.add_synthetic_tick(price=84645.0, timestamp_ms=(ts - 6) * 1000)
    detrade_observer.bar_aggregator.add_synthetic_tick(price=84650.25, timestamp_ms=(ts - 1) * 1000)

    try:
        result = await microstructure_intelligence_service.scan('BTCUSDT', seconds_until_start=5.0)
        assert result.service_available is True
        assert result.reference_price == 84650.25
        assert result.features is not None
        assert result.decision is not None
    finally:
        detrade_observer.latest_tick = None
        detrade_observer.bar_aggregator.clear()


def test_pure_detrade_flat_ticks_produce_neutral_taker_ratio():
    from app.integrations.market_data.five_second_bar import FiveSecondBarAggregator
    agg = FiveSecondBarAggregator(max_bars=60)
    base_ms = 1700000000000

    # Feed 4 identical ticks in the same bar
    agg.add_synthetic_tick(price=84605.00, timestamp_ms=base_ms + 100)
    agg.add_synthetic_tick(price=84605.00, timestamp_ms=base_ms + 1000)
    agg.add_synthetic_tick(price=84605.00, timestamp_ms=base_ms + 2000)
    agg.add_synthetic_tick(price=84605.00, timestamp_ms=base_ms + 3000)

    # Next bar closes previous bar
    closed = agg.add_synthetic_tick(price=84605.00, timestamp_ms=base_ms + 5100)
    assert closed is not None
    assert closed.trades_count == 4
    # All flat ticks must be split 50/50, not 100% buyer!
    assert closed.taker_ratio == 0.50
    assert closed.taker_buy_volume == closed.taker_sell_volume


def test_pure_detrade_tie_rule_vetoes_weak_bullish_returns():
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker("BTCUSDT", 84500.5, 1.0, 84500.5, 1.0, now, "DETRADE_SYNTHETIC")
    
    # 5s bar with weak return (+0.50), below the +1.00 tie hurdle
    bars_5s = [
        FiveSecondBar(
            bucket_ts=ts - 5,
            open=84500.0, high=84502.0, low=84500.0, close=84500.5,
            volume=5.0, quote_volume=5.0 * 84500.0, trades_count=10,
            taker_buy_volume=3.5, taker_sell_volume=1.5, closed=True,
        )
    ]
    bar_metrics = {
        'ema_fast_9': 84501.0,
        'ema_slow_21': 84499.0,
        'rsi_14': 55.0,
        'momentum_3bar_usd': 1.5,
    }
    features = build_microstructure_features(
        latest_book=book, now=now, bars_5s=bars_5s, bar_metrics_5s=bar_metrics, is_synthetic=True,
    )
    score = score_microstructure_features(features, is_synthetic=True)
    decision = decide_microstructure(
        score=score,
        features=features,
        min_score=4,
        min_margin=2,
        min_5s_range=1.00,
        is_synthetic=True,
        up_min_margin=2,
    )

    # Must veto UP because +$0.50 is insufficient to overcome house tie-loss edge
    assert decision.direction == SignalDirection.NO_TRADE
    assert "tie-loss house edge" in decision.reason
    assert decision.stake_recommendation == "🛡️ Skip Round"


def test_pure_detrade_falling_velocity_vetoes_up():
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker("BTCUSDT", 84501.5, 1.0, 84501.5, 1.0, now, "DETRADE_SYNTHETIC")
    
    # Bar closed with +$1.50 return, but live ticks in the last 1s fell from 84504 to 84501.5
    bars_5s = [
        FiveSecondBar(
            bucket_ts=ts - 5,
            open=84500.0, high=84504.0, low=84500.0, close=84501.5,
            volume=10.0, quote_volume=10.0 * 84500.0, trades_count=20,
            taker_buy_volume=7.0, taker_sell_volume=3.0, closed=True,
        )
    ]
    bar_metrics = {
        'ema_fast_9': 84502.0,
        'ema_slow_21': 84499.0,
        'rsi_14': 58.0,
        'momentum_3bar_usd': 2.0,
    }
    from app.integrations.market_data.base import MarketTick
    # Recent ticks show price falling over the last 1 second
    recent_ticks = [
        MarketTick(symbol="BTCUSDT", price=84504.0, quantity=1.0, event_time=now - timedelta(seconds=1), provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
        MarketTick(symbol="BTCUSDT", price=84502.5, quantity=1.0, event_time=now - timedelta(milliseconds=500), provider="DETRADE_SYNTHETIC", is_buyer_maker=True),
        MarketTick(symbol="BTCUSDT", price=84501.5, quantity=1.0, event_time=now, provider="DETRADE_SYNTHETIC", is_buyer_maker=True),
    ]
    features = build_microstructure_features(
        latest_book=book, recent_ticks=recent_ticks, now=now, bars_5s=bars_5s, bar_metrics_5s=bar_metrics, is_synthetic=True,
    )
    score = score_microstructure_features(features, is_synthetic=True)
    decision = decide_microstructure(
        score=score,
        features=features,
        min_score=6,
        min_margin=3,
        min_5s_range=1.00,
        is_synthetic=True,
        up_min_margin=4,
    )

    # Must veto UP because velocity is actively decelerating/dropping
    assert decision.direction == SignalDirection.NO_TRADE
    assert "velocity is decelerating" in decision.reason
    assert decision.stake_recommendation == "🛡️ Skip Round"


