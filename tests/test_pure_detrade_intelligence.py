import pytest
from datetime import datetime, timezone, timedelta

from app.integrations.market_data.base import BookTicker, MarketTick
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
    from app.signals.microstructure.scoring import MicrostructureScoreResult
    score = MicrostructureScoreResult(bull_score=7, bear_score=0, reasons=['bullish impulse'])
    decision = decide_microstructure(
        score=score,
        features=features,
        min_score=6,
        min_margin=3,
        min_5s_range=1.00,
        is_synthetic=True,
        up_min_margin=4,
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
    from app.signals.microstructure.scoring import MicrostructureScoreResult
    score = MicrostructureScoreResult(bull_score=7, bear_score=0, reasons=['bullish impulse'])
    decision = decide_microstructure(
        score=score,
        features=features,
        min_score=6,
        min_margin=3,
        min_5s_range=1.00,
        is_synthetic=True,
        up_min_margin=4,
    )

    # Must veto UP because velocity is actively ticking down
    assert decision.direction == SignalDirection.NO_TRADE
    assert "ticking down" in decision.reason or "velocity" in decision.reason
    assert decision.stake_recommendation == "🛡️ Skip Round"


def test_pure_detrade_drifting_bounce_after_dump_is_strictly_vetoed():
    now = datetime(2026, 10, 3, 8, 2, 48, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker("BTCUSDT", 84537.34, 1.0, 84537.34, 1.0, now, "DETRADE_SYNTHETIC")

    # Bar closed with tiny return (+0.09) and narrow range ($0.40)
    bars_5s = [
        FiveSecondBar(
            bucket_ts=ts - 5,
            open=84537.25, high=84537.40, low=84537.20, close=84537.34,
            volume=3.0, quote_volume=3.0 * 84537.0, trades_count=6,
            taker_buy_volume=1.5, taker_sell_volume=1.5, closed=True,
        )
    ]
    # Macro metrics are bearish from previous dump
    bar_metrics = {
        'ema_fast_9': 84530.0,
        'ema_slow_21': 84550.0,
        'rsi_14': 38.0,
        'momentum_3bar_usd': -5.0,
    }
    from app.integrations.market_data.base import MarketTick
    # Real-time ticks in the last 2s are actually ticking UP (+0.09)
    recent_ticks = [
        MarketTick(symbol="BTCUSDT", price=84537.25, quantity=1.0, event_time=now - timedelta(seconds=2), provider="DETRADE_SYNTHETIC", is_buyer_maker=True),
        MarketTick(symbol="BTCUSDT", price=84537.30, quantity=1.0, event_time=now - timedelta(seconds=1), provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
        MarketTick(symbol="BTCUSDT", price=84537.34, quantity=1.0, event_time=now, provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
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
        min_5s_range=1.50,
        is_synthetic=True,
        up_min_margin=4,
    )

    # Must NOT emit DOWN even though macro trend is bearish!
    assert decision.direction == SignalDirection.NO_TRADE
    assert decision.stake_recommendation == "🛡️ Skip Round"


def test_pure_detrade_station_barrier_proximity_and_velocity():
    now = datetime(2026, 10, 3, 8, 30, 0, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker("BTCUSDT", 84548.00, 1.0, 84548.00, 1.0, now, "DETRADE_SYNTHETIC")
    recent_ticks = [
        MarketTick(symbol="BTCUSDT", price=84545.0, quantity=1.0, event_time=now - timedelta(seconds=2), provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
        MarketTick(symbol="BTCUSDT", price=84546.5, quantity=1.0, event_time=now - timedelta(seconds=1), provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
        MarketTick(symbol="BTCUSDT", price=84548.0, quantity=1.0, event_time=now, provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
    ]
    features = build_microstructure_features(
        latest_book=book,
        recent_ticks=recent_ticks,
        now=now,
        is_synthetic=True,
    )

    # Station boundaries for 84,548.00 in $50 band: [84,500 - 84,550]
    assert features.station_barrier_lower == 84500.0
    assert features.station_barrier_upper == 84550.0
    assert features.station_barrier_dist_upper == 2.0
    assert features.station_barrier_dist_lower == 48.0
    assert features.station_nearest_barrier_dist == 2.0
    assert features.station_nearest_barrier_type == "UPPER"
    assert features.station_channel_progress == pytest.approx(0.96, abs=0.01)

    # Internal velocity and acceleration in USD/sec
    assert features.internal_velocity_usd == pytest.approx(1.50, abs=0.1)
    assert features.internal_acceleration_usd == pytest.approx(0.0, abs=0.2)
    assert features.station_travel_time_seconds is not None
    assert features.station_travel_time_seconds <= 2.0


def test_pure_detrade_bounded_bounce_vetoes_breakout():
    now = datetime(2026, 10, 3, 8, 35, 0, tzinfo=timezone.utc)
    book = BookTicker("BTCUSDT", 84549.60, 1.0, 84549.60, 1.0, now, "DETRADE_SYNTHETIC")
    # Ticks approach upper barrier 84,550.00 and decelerate / reverse downward (-0.40 in last tick)
    recent_ticks = [
        MarketTick(symbol="BTCUSDT", price=84548.0, quantity=1.0, event_time=now - timedelta(seconds=2), provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
        MarketTick(symbol="BTCUSDT", price=84550.0, quantity=1.0, event_time=now - timedelta(seconds=1), provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
        MarketTick(symbol="BTCUSDT", price=84549.60, quantity=1.0, event_time=now, provider="DETRADE_SYNTHETIC", is_buyer_maker=True),
    ]
    features = build_microstructure_features(
        latest_book=book,
        recent_ticks=recent_ticks,
        now=now,
        is_synthetic=True,
    )
    assert features.regime_classification == "BOUNDED_BOUNCE"

    from app.signals.microstructure.scoring import MicrostructureScoreResult
    score = MicrostructureScoreResult(
        bull_score=7,
        bear_score=0,
        reasons=['Bullish impulse toward upper station barrier'],
    )
    decision = decide_microstructure(
        score=score,
        features=features,
        min_score=5,
        min_margin=2,
        min_5s_range=1.00,
        is_synthetic=True,
    )
    # Must veto UP due to ceiling rejection
    assert decision.direction == SignalDirection.NO_TRADE
    assert "barrier" in decision.reason.lower() or "bounce" in decision.reason.lower()


def test_pure_detrade_station_surge_breakout_confirmed():
    now = datetime(2026, 10, 3, 8, 40, 0, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker("BTCUSDT", 84525.00, 1.0, 84525.00, 1.0, now, "DETRADE_SYNTHETIC")
    # Massive surge in middle of channel ($84,500 - $84,550), moving +$3.00 with accelerating velocity
    recent_ticks = [
        MarketTick(symbol="BTCUSDT", price=84521.0, quantity=1.0, event_time=now - timedelta(seconds=2), provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
        MarketTick(symbol="BTCUSDT", price=84522.5, quantity=1.0, event_time=now - timedelta(seconds=1), provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
        MarketTick(symbol="BTCUSDT", price=84525.0, quantity=1.0, event_time=now, provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
    ]
    bars_5s = [
        FiveSecondBar(
            bucket_ts=ts - 5,
            open=84520.0, high=84526.0, low=84520.0, close=84525.0,
            volume=5.0, quote_volume=5.0 * 84525.0, trades_count=8,
            taker_buy_volume=4.0, taker_sell_volume=1.0, closed=True,
        )
    ]
    features = build_microstructure_features(
        latest_book=book,
        recent_ticks=recent_ticks,
        bars_5s=bars_5s,
        now=now,
        is_synthetic=True,
    )
    assert features.regime_classification == "SURGE_BREAKOUT"

    score = score_microstructure_features(features, is_synthetic=True)
    decision = decide_microstructure(
        score=score,
        features=features,
        min_score=5,
        min_margin=2,
        min_5s_range=1.00,
        is_synthetic=True,
    )
    assert decision.direction == SignalDirection.UP
    assert decision.quality == "STRONG"


def test_pure_detrade_phase_alignment_synchronization():
    from app.signals.contracts import RoundPredictionContext
    now = datetime(2026, 10, 3, 8, 45, 0, tzinfo=timezone.utc)
    book = BookTicker("BTCUSDT", 84500.0, 1.0, 84500.0, 1.0, now, "DETRADE_SYNTHETIC")
    context = RoundPredictionContext(
        round_id="147399999",
        current_server_time_ms=int(now.timestamp() * 1000),
        price_start_time_ms=int((now.timestamp() + 2.0) * 1000),
        price_end_time_ms=int((now.timestamp() + 7.0) * 1000),
        trade_cutoff_time_ms=int((now.timestamp() + 1.8) * 1000),
        seconds_until_start=2.0,
        contract_duration_seconds=5.0,
        status=1001,
        phase="BETTING",
        is_fresh=True,
        observed_at=now,
        feed_age_ms=120,
    )
    features = build_microstructure_features(
        latest_book=book,
        now=now,
        is_synthetic=True,
        round_context=context,
    )
    assert features.phase_aligned is True
    assert features.round_phase == "BETTING"
    assert features.round_remaining_seconds == 2.0
    assert features.round_elapsed_seconds == 3.0
    assert features.round_progress_pct == 0.60


def test_pure_detrade_down_signal_generation():
    now = datetime(2026, 10, 3, 8, 50, 0, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker("BTCUSDT", 84520.0, 1.0, 84520.0, 1.0, now, "DETRADE_SYNTHETIC")
    bars_5s = [
        FiveSecondBar(
            bucket_ts=ts - 5,
            open=84522.0, high=84522.5, low=84519.5, close=84520.0,
            volume=6.0, quote_volume=6.0 * 84520.0, trades_count=12,
            taker_buy_volume=1.5, taker_sell_volume=4.5, closed=True,
        )
    ]
    bar_metrics = {
        'ema_fast_9': 84521.0,
        'ema_slow_21': 84525.0,
        'rsi_14': 40.0,
        'momentum_3bar_usd': -2.5,
    }
    features = build_microstructure_features(
        latest_book=book,
        now=now,
        bars_5s=bars_5s,
        bar_metrics_5s=bar_metrics,
        is_synthetic=True,
    )
    score = score_microstructure_features(features, is_synthetic=True)
    decision = decide_microstructure(
        score=score,
        features=features,
        min_score=5,
        min_margin=2,
        min_5s_range=0.80,
        is_synthetic=True,
    )
    assert decision.direction == SignalDirection.DOWN
    assert decision.stake_recommendation in ("🔥 Stake High", "⚡ Stake Low")


def test_pure_detrade_minor_jitter_does_not_veto_strong_up():
    now = datetime(2026, 10, 3, 8, 55, 0, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker("BTCUSDT", 84530.0, 1.0, 84530.0, 1.0, now, "DETRADE_SYNTHETIC")
    bars_5s = [
        FiveSecondBar(
            bucket_ts=ts - 5,
            open=84527.0, high=84531.0, low=84527.0, close=84530.05,
            volume=8.0, quote_volume=8.0 * 84530.0, trades_count=15,
            taker_buy_volume=6.0, taker_sell_volume=2.0, closed=True,
        )
    ]
    bar_metrics = {
        'ema_fast_9': 84529.0,
        'ema_slow_21': 84526.0,
        'rsi_14': 62.0,
        'momentum_3bar_usd': 3.0,
    }
    # Minor 5-cent noise jitter on the last tick (-$0.05)
    recent_ticks = [
        MarketTick(symbol="BTCUSDT", price=84530.10, quantity=1.0, event_time=now - timedelta(seconds=1), provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
        MarketTick(symbol="BTCUSDT", price=84530.05, quantity=1.0, event_time=now, provider="DETRADE_SYNTHETIC", is_buyer_maker=False),
    ]
    features = build_microstructure_features(
        latest_book=book,
        recent_ticks=recent_ticks,
        now=now,
        bars_5s=bars_5s,
        bar_metrics_5s=bar_metrics,
        is_synthetic=True,
    )
    score = score_microstructure_features(features, is_synthetic=True)
    decision = decide_microstructure(
        score=score,
        features=features,
        min_score=5,
        min_margin=2,
        min_5s_range=0.80,
        is_synthetic=True,
        up_min_margin=3,
    )
    # 5-cent noise must NOT veto the strong upward thrust
    assert decision.direction == SignalDirection.UP
    assert decision.quality in ("VALID", "STRONG")


def test_station_barrier_ceiling_buffer_vetoes_up():
    # Price is 81847.0 (within $3.00 of 81850 ceiling barrier)
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker("BTCUSDT", 81847.0, 1.0, 81847.0, 1.0, now, "DETRADE_SYNTHETIC")
    bars_5s = [
        FiveSecondBar(
            bucket_ts=ts - 5,
            open=81845.0, high=81847.5, low=81845.0, close=81847.0,
            volume=5.0, quote_volume=5.0 * 81847.0, trades_count=10,
            taker_buy_volume=4.0, taker_sell_volume=1.0, closed=True,
        )
    ]
    bar_metrics = {
        'ema_fast_9': 81846.0,
        'ema_slow_21': 81842.0,
        'rsi_14': 65.0,
        'momentum_3bar_usd': 3.0,
    }
    features = build_microstructure_features(
        latest_book=book, now=now, bars_5s=bars_5s, bar_metrics_5s=bar_metrics, is_synthetic=True,
    )
    score = score_microstructure_features(features, is_synthetic=True)
    decision = decide_microstructure(
        score=score,
        features=features,
        min_score=5,
        min_margin=2,
        is_synthetic=True,
    )
    # Must veto UP due to proximity to 81850 ceiling
    assert decision.direction == SignalDirection.NO_TRADE
    assert "station ceiling" in decision.reason.lower()


def test_micro_chop_return_filter_vetoes_weak_drift():
    # 5s return is only $0.65 with weak 30s drift ($1.00)
    now = datetime(2026, 10, 3, 6, 0, 0, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker("BTCUSDT", 81820.0, 1.0, 81820.0, 1.0, now, "DETRADE_SYNTHETIC")
    bars_5s = [
        FiveSecondBar(
            bucket_ts=ts - 5,
            open=81819.35, high=81820.5, low=81819.35, close=81820.0,
            volume=5.0, quote_volume=5.0 * 81820.0, trades_count=10,
            taker_buy_volume=4.0, taker_sell_volume=1.0, closed=True,
        )
    ]
    bar_metrics = {
        'ema_fast_9': 81820.0,
        'ema_slow_21': 81819.0,
        'rsi_14': 58.0,
        'momentum_3bar_usd': 0.8,
    }
    features = build_microstructure_features(
        latest_book=book, now=now, bars_5s=bars_5s, bar_metrics_5s=bar_metrics, is_synthetic=True,
    )
    score = score_microstructure_features(features, is_synthetic=True)
    decision = decide_microstructure(
        score=score,
        features=features,
        min_score=5,
        min_margin=2,
        is_synthetic=True,
    )
    # Must veto UP due to insufficient return (< $0.90)
    assert decision.direction == SignalDirection.NO_TRADE
    assert "insufficient" in decision.reason.lower()





