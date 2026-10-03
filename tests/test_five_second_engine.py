import pytest
from datetime import datetime, timedelta, timezone

from app.integrations.market_data.base import BookTicker, DepthSnapshot, MarketTick
from app.integrations.market_data.five_second_bar import FiveSecondBar, FiveSecondBarAggregator
from app.models.entities import SignalDirection
from app.services.market_data import MicrostructureDataCache
from app.services.microstructure_intelligence import MicrostructureIntelligenceService
from app.signals.microstructure.decision import decide_microstructure
from app.signals.microstructure.features import (
    MicrostructureFeatureSnapshot,
    build_microstructure_features,
)
from app.signals.microstructure.scoring import score_microstructure_features


def test_five_second_bar_properties():
    bar = FiveSecondBar(
        bucket_ts=1700000000,
        open=90000.0,
        high=90015.0,
        low=89995.0,
        close=90010.0,
        volume=10.0,
        quote_volume=900000.0,
        trades_count=25,
        taker_buy_volume=7.0,
        taker_sell_volume=3.0,
    )
    assert bar.range == pytest.approx(20.0)
    assert bar.return_usd == pytest.approx(10.0)
    assert bar.return_bps == pytest.approx((10.0 / 90000.0) * 10000.0)
    assert bar.taker_ratio == pytest.approx(0.70)
    assert bar.is_bullish is True
    assert bar.is_bearish is False
    assert bar.is_flat is False

    d = bar.to_dict()
    assert d['range'] == 20.0
    assert d['return_usd'] == 10.0
    assert d['taker_ratio'] == 0.7


def test_five_second_bar_aggregator_rollover_and_indicators():
    agg = FiveSecondBarAggregator(max_bars=60)
    base_ts = 1700000000.0

    # Feed 20 consecutive 5s bars of trades
    price = 90000.0
    for i in range(20):
        bar_ts = base_ts + (i * 5)
        # 3 trades per bar
        agg.add_trade(price, 1.0, False, bar_ts + 0.1)
        agg.add_trade(price + 2.0, 2.0, False, bar_ts + 2.0)
        price += 3.0
        agg.add_trade(price, 1.0, False, bar_ts + 4.5)

    # Roll over the last bar by introducing a trade in bucket 20
    agg.add_trade(price + 1.0, 1.0, False, base_ts + 100.1)

    closed = agg.get_closed_bars()
    assert len(closed) == 20
    assert closed[-1].bucket_ts == int(base_ts + 95)
    assert closed[0].bucket_ts == int(base_ts)

    ema9 = agg.calc_ema(9)
    ema21 = agg.calc_ema(21)
    rsi14 = agg.calc_rsi(14)
    mom3 = agg.calc_momentum(3)
    avg_rng = agg.calc_average_range(6)

    assert ema9 is not None and ema9 > 90000.0
    assert mom3 is not None and mom3 > 0.0
    assert avg_rng is not None and avg_rng > 0.0

    metrics = agg.get_metrics()
    assert metrics['closed_bars_count'] == 20
    assert metrics['trend_5s'] == 'BULLISH'


@pytest.mark.asyncio
async def test_microstructure_cache_integrates_5s_aggregator():
    cache = MicrostructureDataCache()
    base_ts = 1700000000.0

    # Add trades
    t1 = MarketTick("BTCUSDT", 91000.0, 1.5, datetime.fromtimestamp(base_ts + 0.5, tz=timezone.utc), "BINANCE", False)
    t2 = MarketTick("BTCUSDT", 91005.0, 2.0, datetime.fromtimestamp(base_ts + 2.0, tz=timezone.utc), "BINANCE", False)
    t3 = MarketTick("BTCUSDT", 91010.0, 1.0, datetime.fromtimestamp(base_ts + 5.5, tz=timezone.utc), "BINANCE", False)

    await cache.add_trade(t1)
    await cache.add_trade(t2)
    await cache.add_trade(t3)

    closed_bars = await cache.get_5s_bars("BTCUSDT")
    assert len(closed_bars) == 1
    assert closed_bars[0].open == 91000.0
    assert closed_bars[0].close == 91005.0
    assert closed_bars[0].range == 5.0

    metrics = await cache.get_5s_metrics("BTCUSDT")
    assert metrics['closed_bars_count'] == 1


def test_microstructure_features_without_1m_candles():
    base_ts = 1700000000.0
    now = datetime.fromtimestamp(base_ts + 6.0, tz=timezone.utc)
    ticks = [
        MarketTick("BTCUSDT", 90000.0, 1.0, datetime.fromtimestamp(base_ts + 0.5, tz=timezone.utc), "B", False),
        MarketTick("BTCUSDT", 90005.0, 2.0, datetime.fromtimestamp(base_ts + 4.0, tz=timezone.utc), "B", False),
        MarketTick("BTCUSDT", 90008.0, 1.0, datetime.fromtimestamp(base_ts + 5.5, tz=timezone.utc), "B", False),
    ]
    book = BookTicker("BTCUSDT", 90007.5, 2.0, 90008.5, 1.0, now, "B")

    # Call build_microstructure_features with candles=None! Must not fail!
    features = build_microstructure_features(
        candles=None,
        latest_book=book,
        recent_ticks=ticks,
        now=now,
    )
    assert features.mid_price == pytest.approx(90008.0)
    assert features.bar_5s_return == pytest.approx(5.0)
    assert features.structure == "BULLISH"


def test_5s_range_gates():
    # 1. Flat chop veto: range < 1.0
    flat_features = MicrostructureFeatureSnapshot(
        ema_fast=90000.0, ema_slow=90000.0, rsi_14=50.0, atr_14_pct=0.01,
        momentum_5m_pct=0.0, structure="FLAT", mid_price=90000.0, spread=0.5,
        spread_bps=0.5, obi_top=0.5, obi_l5=0.5, microprice=90000.5, microprice_dev_bps=0.5,
        tfi_1s=0.5, tfi_5s=0.5, trade_count_1s=5, trade_count_5s=10, volume_5s=5.0,
        return_250ms_bps=1.0, return_500ms_bps=1.0, return_1s_bps=1.0, return_2s_bps=1.0,
        return_5s_bps=1.0, velocity_1s_bps=2.0, acceleration_1s_bps=1.0,
        bid_depth_l5_qty=5.0, ask_depth_l5_qty=5.0, liquidity_delta_l5_pct=0.0,
        bar_5s_return=0.20, bar_5s_range=0.30, bar_5s_taker_ratio=0.80,
    )
    score_flat = score_microstructure_features(flat_features)
    decision_flat = decide_microstructure(score_flat, flat_features, min_5s_range=1.0)
    assert decision_flat.direction == SignalDirection.NO_TRADE
    assert "range is too narrow" in decision_flat.reason

    # 2. Parabolic exhaustion veto: range > 12.0
    exhaust_features = MicrostructureFeatureSnapshot(
        ema_fast=90000.0, ema_slow=90000.0, rsi_14=50.0, atr_14_pct=0.01,
        momentum_5m_pct=0.0, structure="FLAT", mid_price=90000.0, spread=0.5,
        spread_bps=0.5, obi_top=0.5, obi_l5=0.5, microprice=90000.5, microprice_dev_bps=0.5,
        tfi_1s=0.5, tfi_5s=0.5, trade_count_1s=5, trade_count_5s=10, volume_5s=5.0,
        return_250ms_bps=1.0, return_500ms_bps=1.0, return_1s_bps=1.0, return_2s_bps=1.0,
        return_5s_bps=1.0, velocity_1s_bps=2.0, acceleration_1s_bps=1.0,
        bid_depth_l5_qty=5.0, ask_depth_l5_qty=5.0, liquidity_delta_l5_pct=0.0,
        bar_5s_return=14.0, bar_5s_range=15.0, bar_5s_taker_ratio=0.90,
    )
    score_exhaust = score_microstructure_features(exhaust_features)
    decision_exhaust = decide_microstructure(score_exhaust, exhaust_features, max_5s_range=12.0)
    assert decision_exhaust.direction == SignalDirection.NO_TRADE
    assert "overextended" in decision_exhaust.reason


def test_add_synthetic_tick_aggregation():
    agg = FiveSecondBarAggregator(max_bars=60)
    base_ms = 1700000000000

    # 1. First tick establishes baseline
    agg.add_synthetic_tick(price=83000.0, timestamp_ms=base_ms + 100)
    # 2. Second tick in same 5s bar with upward movement (inferred buyer)
    agg.add_synthetic_tick(price=83005.0, timestamp_ms=base_ms + 2500)
    # 3. Third tick rolls into the next 5s bar
    closed = agg.add_synthetic_tick(price=83012.0, timestamp_ms=base_ms + 5200)

    assert closed is not None
    assert closed.open == 83000.0
    assert closed.close == 83005.0
    assert closed.high == 83005.0
    assert closed.low == 83000.0
    assert closed.range == 5.0
    assert closed.return_usd == 5.0
    assert closed.taker_ratio >= 0.75  # Inferred buyer because price rose


@pytest.mark.asyncio
async def test_microstructure_cache_add_synthetic_tick():
    cache = MicrostructureDataCache()
    base_ms = 1700000000000

    await cache.add_synthetic_tick(price=83100.0, timestamp_ms=base_ms, symbol="BTCUSDT")
    await cache.add_synthetic_tick(price=83110.0, timestamp_ms=base_ms + 2000, symbol="BTCUSDT")
    await cache.add_synthetic_tick(price=83120.0, timestamp_ms=base_ms + 6000, symbol="BTCUSDT")

    bars = await cache.get_5s_bars("BTCUSDT")
    assert len(bars) == 1
    assert bars[0].open == 83100.0
    assert bars[0].close == 83110.0


def test_detrade_stake_room_range_calibration():
    # In $50-$100 room: min_5s_range is $2.50 and max_5s_range is $45.00
    # A $15.00 move should be accepted (not vetoed) when score is strong
    active_features = MicrostructureFeatureSnapshot(
        ema_fast=90020.0, ema_slow=90000.0, rsi_14=60.0, atr_14_pct=0.01,
        momentum_5m_pct=0.05, structure="BULLISH", mid_price=90020.0, spread=0.5,
        spread_bps=0.5, obi_top=0.7, obi_l5=0.8, microprice=90021.0, microprice_dev_bps=1.0,
        tfi_1s=0.8, tfi_5s=0.75, trade_count_1s=15, trade_count_5s=40, volume_5s=15.0,
        return_250ms_bps=2.0, return_500ms_bps=3.0, return_1s_bps=5.0, return_2s_bps=8.0,
        return_5s_bps=15.0, velocity_1s_bps=5.0, acceleration_1s_bps=2.0,
        bid_depth_l5_qty=10.0, ask_depth_l5_qty=3.0, liquidity_delta_l5_pct=0.3,
        bar_5s_return=12.0, bar_5s_range=15.0, bar_5s_taker_ratio=0.85,
    )
    score = score_microstructure_features(active_features)
    # Under default 12.0 max, this was vetoed as overextended
    dec_old = decide_microstructure(score, active_features, max_5s_range=12.0)
    assert dec_old.direction == SignalDirection.NO_TRADE

    # Under $50-$100 calibrated range (max 45.0), this is qualified UP!
    dec_new = decide_microstructure(score, active_features, min_5s_range=2.50, max_5s_range=45.0)
    assert dec_new.direction == SignalDirection.UP


def test_detrade_pure_synthetic_scoring_decoupled_from_binance():
    # Binance OBI is neutral/empty (0.0) and Binance trades are absent (None)
    # DeTrade synthetic bar and velocity provide 100% of the directional evidence
    synth_features = MicrostructureFeatureSnapshot(
        ema_fast=90020.0, ema_slow=90000.0, rsi_14=55.0, atr_14_pct=0.01,
        momentum_5m_pct=0.05, structure="BULLISH", mid_price=90020.0, spread=0.0,
        spread_bps=0.0, obi_top=0.0, obi_l5=0.0, microprice=90020.0, microprice_dev_bps=0.0,
        tfi_1s=None, tfi_5s=None, trade_count_1s=0, trade_count_5s=0, volume_5s=0.0,
        return_250ms_bps=2.0, return_500ms_bps=2.5, return_1s_bps=3.0, return_2s_bps=5.0,
        return_5s_bps=8.0, velocity_1s_bps=3.0, acceleration_1s_bps=1.0,
        bid_depth_l5_qty=0.0, ask_depth_l5_qty=0.0, liquidity_delta_l5_pct=0.0,
        bar_5s_return=3.50, bar_5s_range=5.00, bar_5s_taker_ratio=0.75,
        bar_5s_ema_fast=90025.0, bar_5s_ema_slow=90010.0, bar_5s_rsi_14=58.0,
        bar_5s_momentum_3bar=4.00,
    )
    score = score_microstructure_features(synth_features, is_synthetic=True)
    # Pure synthetic scoring awards points for bar impulse, momentum, trend, and velocity
    assert score.bull_score >= 8
    assert score.bear_score == 0

    # Decision succeeds without Binance order book spread or depth checks
    dec = decide_microstructure(
        score, synth_features, is_synthetic=True, min_score=7, min_margin=4, min_5s_range=2.0, max_5s_range=25.0
    )
    assert dec.direction == SignalDirection.UP
    assert dec.quality in ("VALID", "STRONG")


def test_detrade_parabolic_spike_exhaustion_veto():
    # Pre-start countdown experiences an excessive parabolic surge ($18.00 return, RSI 75)
    # Buying at this top sets the contract Start Price at the peak, risking an instant retracement loss
    spike_features = MicrostructureFeatureSnapshot(
        ema_fast=90050.0, ema_slow=90000.0, rsi_14=70.0, atr_14_pct=0.01,
        momentum_5m_pct=0.15, structure="BULLISH", mid_price=90050.0, spread=0.0,
        spread_bps=0.0, obi_top=0.0, obi_l5=0.0, microprice=90050.0, microprice_dev_bps=0.0,
        tfi_1s=None, tfi_5s=None, trade_count_1s=0, trade_count_5s=0, volume_5s=0.0,
        return_250ms_bps=5.0, return_500ms_bps=8.0, return_1s_bps=12.0, return_2s_bps=15.0,
        return_5s_bps=20.0, velocity_1s_bps=12.0, acceleration_1s_bps=3.0,
        bid_depth_l5_qty=0.0, ask_depth_l5_qty=0.0, liquidity_delta_l5_pct=0.0,
        bar_5s_return=18.00, bar_5s_range=20.00, bar_5s_taker_ratio=0.90,
        bar_5s_ema_fast=90045.0, bar_5s_ema_slow=90010.0, bar_5s_rsi_14=75.0,
        bar_5s_momentum_3bar=12.00,
    )
    score = score_microstructure_features(spike_features, is_synthetic=True)
    dec = decide_microstructure(
        score, spike_features, is_synthetic=True, min_score=7, min_margin=4,
        min_5s_range=2.0, max_5s_range=25.0, max_lead_impulse=16.0
    )
    assert dec.direction == SignalDirection.NO_TRADE
    assert "exhaustion" in dec.reason.lower() or "overextended" in dec.reason.lower()


def test_detrade_asymmetric_tie_margin_protection():
    # Score has margin = 4 (bull 7, bear 3)
    # Under DeTrade asymmetric rules, End <= Start awards ties to DOWN
    # UP requires up_min_margin = 5 to overcome this house edge
    features = MicrostructureFeatureSnapshot(
        ema_fast=90020.0, ema_slow=90000.0, rsi_14=55.0, atr_14_pct=0.01,
        momentum_5m_pct=0.05, structure="BULLISH", mid_price=90020.0, spread=0.0,
        spread_bps=0.0, obi_top=0.0, obi_l5=0.0, microprice=90020.0, microprice_dev_bps=0.0,
        tfi_1s=None, tfi_5s=None, trade_count_1s=0, trade_count_5s=0, volume_5s=0.0,
        return_250ms_bps=1.0, return_500ms_bps=1.5, return_1s_bps=2.0, return_2s_bps=3.0,
        return_5s_bps=4.0, velocity_1s_bps=2.0, acceleration_1s_bps=0.5,
        bid_depth_l5_qty=0.0, ask_depth_l5_qty=0.0, liquidity_delta_l5_pct=0.0,
        bar_5s_return=2.50, bar_5s_range=4.00, bar_5s_taker_ratio=0.65,
        bar_5s_ema_fast=90022.0, bar_5s_ema_slow=90015.0, bar_5s_rsi_14=55.0,
        bar_5s_momentum_3bar=3.00,
    )
    from app.signals.microstructure.scoring import MicrostructureScoreResult
    marginal_score = MicrostructureScoreResult(bull_score=7, bear_score=3, reasons=['bullish edge'])

    # With up_min_margin = 5, margin of 4 is rejected as insufficient
    dec_rejected = decide_microstructure(
        marginal_score, features, is_synthetic=True, min_score=7, min_margin=4,
        up_min_margin=5, min_5s_range=2.0, max_5s_range=25.0
    )
    assert dec_rejected.direction == SignalDirection.NO_TRADE

    # With bull_score = 8 (margin = 5), UP is approved
    stronger_score = MicrostructureScoreResult(bull_score=8, bear_score=3, reasons=['strong bullish edge'])
    dec_approved = decide_microstructure(
        stronger_score, features, is_synthetic=True, min_score=7, min_margin=4,
        up_min_margin=5, min_5s_range=2.0, max_5s_range=25.0
    )
    assert dec_approved.direction == SignalDirection.UP
    assert dec_approved.stake_tier == 'PRIME'
    assert 'Stake High' in dec_approved.stake_recommendation


def test_countdown_execution_window_gate():
    features = MicrostructureFeatureSnapshot(
        ema_fast=90020.0, ema_slow=90000.0, rsi_14=55.0, atr_14_pct=0.01,
        momentum_5m_pct=0.05, structure="BULLISH", mid_price=90020.0, spread=0.0,
        spread_bps=0.0, obi_top=0.0, obi_l5=0.0, microprice=90020.0, microprice_dev_bps=0.0,
        tfi_1s=None, tfi_5s=None, trade_count_1s=0, trade_count_5s=0, volume_5s=0.0,
        return_250ms_bps=1.0, return_500ms_bps=1.5, return_1s_bps=2.0, return_2s_bps=3.0,
        return_5s_bps=4.0, velocity_1s_bps=2.0, acceleration_1s_bps=0.5,
        bid_depth_l5_qty=0.0, ask_depth_l5_qty=0.0, liquidity_delta_l5_pct=0.0,
        bar_5s_return=2.50, bar_5s_range=4.00, bar_5s_taker_ratio=0.65,
        bar_5s_ema_fast=90022.0, bar_5s_ema_slow=90015.0, bar_5s_rsi_14=55.0,
        bar_5s_momentum_3bar=3.00,
    )
    from app.signals.microstructure.scoring import MicrostructureScoreResult
    strong_score = MicrostructureScoreResult(bull_score=8, bear_score=2, reasons=['strong bullish edge'])

    # When 0.0s remain (round has started), signal is vetoed
    dec_too_late = decide_microstructure(
        strong_score, features, is_synthetic=True, min_score=7, min_margin=4,
        seconds_until_start=0.0
    )
    assert dec_too_late.direction == SignalDirection.NO_TRADE
    assert 'already started' in dec_too_late.reason
    assert dec_too_late.stake_tier == 'DEFENSIVE'

    # When 1.5 seconds remain (even close to start), signal is approved with Prime stake guidance
    dec_in_time = decide_microstructure(
        strong_score, features, is_synthetic=True, min_score=7, min_margin=4,
        seconds_until_start=1.5
    )
    assert dec_in_time.direction == SignalDirection.UP
    assert dec_in_time.stake_tier == 'PRIME'
    assert 'Stake High' in dec_in_time.stake_recommendation



