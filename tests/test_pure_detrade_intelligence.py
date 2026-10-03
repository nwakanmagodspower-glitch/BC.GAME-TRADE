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
