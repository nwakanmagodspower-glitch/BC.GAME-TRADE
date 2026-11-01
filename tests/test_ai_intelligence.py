from __future__ import annotations

from datetime import datetime, timezone
import pytest

from app.integrations.market_data.base import BookTicker
from app.integrations.market_data.five_second_bar import FiveSecondBar
from app.services.ai_intelligence import ai_microstructure_predictor
from app.signals.microstructure.features import (
    MicrostructureFeatureSnapshot,
    build_microstructure_features,
)


def _base_features(**kwargs) -> MicrostructureFeatureSnapshot:
    now = datetime(2026, 10, 31, 20, 5, 0, tzinfo=timezone.utc)
    ts = int(now.timestamp())
    book = BookTicker("BTCUSDT", 77580.0, 1.0, 77580.0, 1.0, now, "DETRADE_SYNTHETIC")
    bars = [
        FiveSecondBar(
            bucket_ts=ts - 5,
            open=77579.0, high=77580.5, low=77579.0, close=77580.0,
            volume=5.0, quote_volume=5.0 * 77580.0, trades_count=10,
            taker_buy_volume=3.5, taker_sell_volume=1.5, closed=True,
        )
    ]
    feats = build_microstructure_features(latest_book=book, now=now, bars_5s=bars, is_synthetic=True)
    d = feats.to_dict()
    d.update(kwargs)
    return MicrostructureFeatureSnapshot(**d)


def test_ai_predicts_laminar_buyer_thrust():
    f = _base_features(
        bar_5s_return=1.50,
        delta_5s_usd=1.80,
        delta_10s_usd=2.50,
        internal_velocity_usd=0.35,
        internal_acceleration_usd=0.10,
        fractal_efficiency_5s=0.75,
        bar_5s_taker_ratio=0.70,
    )
    res = ai_microstructure_predictor.predict(f)
    assert res.predicted_direction == "UP"
    assert res.up_probability >= 0.70
    assert res.ai_regime == "LAMINAR_THRUST"
    assert res.risk_score <= 3


def test_ai_predicts_exhaustion_top_reversal():
    # Price pumped $6.50 over 10s and is stalling/pulling back from extremum
    f = _base_features(
        bar_5s_return=2.50,
        delta_5s_usd=4.50,
        delta_10s_usd=6.50,
        internal_velocity_usd=0.05,
        internal_acceleration_usd=-0.25,
        pullback_from_extremum=0.55,
        fractal_efficiency_5s=0.60,
    )
    res = ai_microstructure_predictor.predict(f)
    assert res.predicted_direction == "DOWN"
    assert res.ai_regime == "EXHAUSTION_TOP"
    assert "exhaustion top" in res.reasoning.lower()


def test_ai_predicts_exhaustion_bottom_bounce():
    # Price dumped -$6.50 over 10s and is stalling/bouncing
    f = _base_features(
        bar_5s_return=-2.50,
        delta_5s_usd=-4.50,
        delta_10s_usd=-6.50,
        internal_velocity_usd=-0.05,
        internal_acceleration_usd=0.25,
        pullback_from_extremum=0.55,
        fractal_efficiency_5s=0.60,
    )
    res = ai_microstructure_predictor.predict(f)
    assert res.predicted_direction == "UP"
    assert res.ai_regime == "EXHAUSTION_BOTTOM"
    assert "exhaustion bottom" in res.reasoning.lower()


def test_ai_filters_micro_chop_defense():
    f = _base_features(
        bar_5s_return=0.05,
        bar_5s_range=0.18,
        lead_range_dollars=0.18,
        range_20s=0.22,
        delta_5s_usd=0.04,
        delta_10s_usd=0.08,
        internal_velocity_usd=0.02,
        internal_acceleration_usd=0.00,
        fractal_efficiency_5s=0.20,
    )
    res = ai_microstructure_predictor.predict(f)
    assert res.predicted_direction == "NO_TRADE"
    assert res.ai_regime == "MICRO_CHOP"
    assert "micro-chop" in res.reasoning.lower()

