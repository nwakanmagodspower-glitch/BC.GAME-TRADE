from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.bot.signal_views import format_signal
from app.integrations.market_data.base import Candle, MarketTick
from app.models.entities import Signal, SignalDirection, SignalStatus
from app.signals.contracts import PredictionTarget, ScanStage
from app.signals.decision import decide
from app.signals.features import FeatureSnapshot, build_features
from app.signals.scoring import ScoreResult, score_features


def _dummy_feature_snapshot(
    lead_range: float = 2.00,
    lead_mom: float = 1.20,
    trade_count: int = 12,
    buy_ratio: float = 0.65,
    ema_fast: float = 65100.0,
    ema_slow: float = 65000.0,
) -> FeatureSnapshot:
    return FeatureSnapshot(
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi_14=60.0,
        atr_14_pct=0.15,
        momentum_5_pct=0.12,
        volume_ratio=1.3,
        taker_buy_ratio=0.60,
        structure='BULLISH',
        distance_to_recent_high_pct=0.05,
        distance_to_recent_low_pct=0.10,
        trade_buy_ratio=buy_ratio,
        trade_count_recent=trade_count,
        lead_range_dollars=lead_range,
        lead_mom_dollars=lead_mom,
        lead_speed_sec=lead_range / 5.0,
    )


def test_low_speed_veto_blocks_trade_during_quiet_chop():
    """Even if scores are high, a low range (< $1.50) must trigger LOW_SPEED NO_TRADE."""
    features = _dummy_feature_snapshot(lead_range=0.75, lead_mom=0.20)
    score = ScoreResult(bull_score=8, bear_score=0, reasons=['strong trend', 'high volume'])

    decision = decide(
        score,
        min_score=5,
        min_margin=2,
        features=features,
        min_lead_range=1.50,
    )

    assert decision.direction == SignalDirection.NO_TRADE
    assert decision.quality == 'LOW_SPEED'
    assert 'BTC range $0.75 < $1.50' in decision.reason
    assert 'Preserving balance from flat chop losses' in decision.reason


def test_active_speed_allows_trade_when_confluent():
    """When lead range >= $1.50 and scores meet thresholds, trade is approved."""
    features = _dummy_feature_snapshot(lead_range=3.20, lead_mom=2.10)
    score = ScoreResult(bull_score=6, bear_score=1, reasons=['trend continuation', 'lead momentum active'])

    decision = decide(
        score,
        min_score=5,
        min_margin=2,
        features=features,
        min_lead_range=1.50,
    )

    assert decision.direction == SignalDirection.UP
    assert decision.quality == 'STRONG'
    assert decision.margin == 5


def test_strict_min_score_and_margin_filters_low_conviction():
    """Score < 5 or margin < 2 must return NO_TRADE."""
    features = _dummy_feature_snapshot(lead_range=2.50)

    # Bull score 4 is below min_score 5
    score_low = ScoreResult(bull_score=4, bear_score=1, reasons=['moderate trend'])
    decision1 = decide(score_low, min_score=5, min_margin=2, features=features, min_lead_range=1.50)
    assert decision1.direction == SignalDirection.NO_TRADE
    assert decision1.quality == 'NO_TRADE'

    # Margin 1 is below min_margin 2 (bull=5, bear=4)
    score_tight = ScoreResult(bull_score=5, bear_score=4, reasons=['competing forces'])
    decision2 = decide(score_tight, min_score=5, min_margin=2, features=features, min_lead_range=1.50)
    assert decision2.direction == SignalDirection.NO_TRADE
    assert decision2.quality == 'NO_TRADE'


def test_scoring_awards_lead_momentum_and_penalizes_sub_dollar_chop():
    # Expanding range awards bonus point
    feat_expanding = _dummy_feature_snapshot(lead_range=2.50, lead_mom=1.10)
    score_exp = score_features(feat_expanding)
    assert any('lead price expansion favors buyers' in r for r in score_exp.reasons)

    # Sub-dollar range penalizes conviction
    feat_sub = _dummy_feature_snapshot(lead_range=0.50, lead_mom=0.10)
    score_sub = score_features(feat_sub)
    assert any('indicates quiet chop' in r for r in score_sub.reasons)


def test_telegram_formatting_low_speed_educates_user():
    signal = Signal(
        direction=SignalDirection.NO_TRADE,
        status=SignalStatus.NO_TRADE,
        strategy_version='BTC_ORIGINAL_INTELLIGENCE_TIMER_V1',
        features_snapshot={
            '_decision': {'quality': 'LOW_SPEED', 'bull_score': 3, 'bear_score': 1},
            'lead_range_dollars': 0.65,
        },
    )

    rendered = format_signal(signal)
    assert '⚪ NO TRADE — Low Market Speed' in rendered
    assert '📊 BTC Speed: $0.65 range (Flat Chop)' in rendered
    assert 'Skipping preserves your balance until clean momentum returns.' in rendered


def test_telegram_formatting_active_signal_displays_momentum_range():
    signal = Signal(
        direction=SignalDirection.UP,
        status=SignalStatus.ACTIVE,
        strategy_version='BTC_ORIGINAL_INTELLIGENCE_TIMER_V1',
        features_snapshot={
            '_decision': {'quality': 'STRONG', 'bull_score': 6, 'bear_score': 0},
            'lead_range_dollars': 3.45,
            '_bcgame_round': {'source': 'DETRADE_SYNC', 'remaining_seconds_at_scan': 9.2},
        },
    )

    rendered = format_signal(signal)
    assert '🟢 UP SIGNAL' in rendered
    assert '🔥 Strength: STRONG • 85% (Triple Confluence)' in rendered
    assert '📊 Momentum Range: $3.45 expansion' in rendered
    assert '⏱️ Entry window: ~9.2s' in rendered
