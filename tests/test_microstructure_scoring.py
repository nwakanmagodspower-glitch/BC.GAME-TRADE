from datetime import datetime, timezone

from app.models.entities import SignalDirection
from app.signals.microstructure.decision import decide_microstructure
from app.signals.microstructure.features import MicrostructureFeatureSnapshot
from app.signals.microstructure.scoring import score_microstructure_features


def create_feature_snapshot(
    *,
    ema_fast=90010.0,
    ema_slow=90000.0,
    rsi_14=55.0,
    atr_14_pct=0.1,
    return_500ms_bps=2.0,
    velocity_1s_bps=2.5,
    acceleration_1s_bps=1.0,
    obi_l5=0.40,
    microprice_dev_bps=1.0,
    tfi_1s=0.60,
    trade_count_1s=5,
    spread_bps=0.5,
    bid_depth_l5_qty=5.0,
    ask_depth_l5_qty=5.0,
) -> MicrostructureFeatureSnapshot:
    return MicrostructureFeatureSnapshot(
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi_14=rsi_14,
        atr_14_pct=atr_14_pct,
        momentum_5m_pct=0.15,
        structure="BULLISH",
        mid_price=90000.0,
        spread=0.5,
        spread_bps=spread_bps,
        obi_top=obi_l5,
        obi_l5=obi_l5,
        microprice=90001.0,
        microprice_dev_bps=microprice_dev_bps,
        tfi_1s=tfi_1s,
        tfi_5s=tfi_1s,
        trade_count_1s=trade_count_1s,
        trade_count_5s=trade_count_1s,
        volume_5s=10.0,
        return_250ms_bps=1.0,
        return_500ms_bps=return_500ms_bps,
        return_1s_bps=velocity_1s_bps,
        return_2s_bps=2.0,
        return_5s_bps=3.0,
        velocity_1s_bps=velocity_1s_bps,
        acceleration_1s_bps=acceleration_1s_bps,
        bid_depth_l5_qty=bid_depth_l5_qty,
        ask_depth_l5_qty=ask_depth_l5_qty,
        liquidity_delta_l5_pct=0.0,
    )


def test_bullish_scoring_and_decision():
    features = create_feature_snapshot()
    score = score_microstructure_features(features)
    assert score.bull_score >= 8
    assert score.bear_score == 0

    decision = decide_microstructure(score, features, min_score=7, min_margin=4)
    assert decision.direction == SignalDirection.UP
    assert decision.quality in ("VALID", "STRONG")


def test_stale_data_veto():
    features = create_feature_snapshot()
    score = score_microstructure_features(features)
    decision = decide_microstructure(score, features, is_fresh=False)
    assert decision.direction == SignalDirection.NO_TRADE
    assert "stale or missing" in decision.reason.lower()


def test_wide_spread_veto():
    features = create_feature_snapshot(spread_bps=5.0)
    score = score_microstructure_features(features)
    decision = decide_microstructure(score, features, max_spread_bps=3.0)
    assert decision.direction == SignalDirection.NO_TRADE
    assert "spread too wide" in decision.reason.lower()


def test_thin_depth_veto():
    features = create_feature_snapshot(bid_depth_l5_qty=0.01, ask_depth_l5_qty=0.01)
    score = score_microstructure_features(features)
    decision = decide_microstructure(score, features, min_l5_volume=0.1)
    assert decision.direction == SignalDirection.NO_TRADE
    assert "depth too thin" in decision.reason.lower()


def test_fast_slow_conflict_veto():
    # Strong fast bullish signals but bearish slow regime
    features = create_feature_snapshot(
        ema_fast=89990.0,
        ema_slow=90010.0,
    )
    # Force negative 5m momentum
    features_dict = features.to_dict()
    features_dict["momentum_5m_pct"] = -0.20
    features = MicrostructureFeatureSnapshot(**features_dict)

    score = score_microstructure_features(features)
    decision = decide_microstructure(score, features, min_score=5, min_margin=3)
    assert decision.direction == SignalDirection.NO_TRADE
    assert "conflicts strongly" in decision.reason.lower()
