from __future__ import annotations

from dataclasses import dataclass

from app.signals.features import FeatureSnapshot


@dataclass(frozen=True)
class ScoreResult:
    bull_score: int
    bear_score: int
    reasons: list[str]


def score_features(features: FeatureSnapshot) -> ScoreResult:
    bull = 0
    bear = 0
    reasons: list[str] = []

    if features.ema_fast > features.ema_slow:
        bull += 2
        reasons.append('fast EMA above slow EMA')
    elif features.ema_fast < features.ema_slow:
        bear += 2
        reasons.append('fast EMA below slow EMA')

    if features.momentum_5_pct >= 0.08:
        bull += 2
        reasons.append('positive 5-minute momentum')
    elif features.momentum_5_pct <= -0.08:
        bear += 2
        reasons.append('negative 5-minute momentum')

    if features.structure == 'BULLISH':
        bull += 2
        reasons.append('bullish short-term structure')
    elif features.structure == 'BEARISH':
        bear += 2
        reasons.append('bearish short-term structure')

    if features.volume_ratio >= 1.20:
        if features.taker_buy_ratio >= 0.55:
            bull += 1
            reasons.append('volume expansion with taker buying')
        elif features.taker_buy_ratio <= 0.45:
            bear += 1
            reasons.append('volume expansion with taker selling')

    if features.trade_buy_ratio is not None and features.trade_count_recent >= 10:
        if features.trade_buy_ratio >= 0.58:
            bull += 2
            reasons.append('recent trade flow favors buyers')
        elif features.trade_buy_ratio <= 0.42:
            bear += 2
            reasons.append('recent trade flow favors sellers')

    if 52 <= features.rsi_14 <= 72:
        bull += 1
        reasons.append('RSI supports bullish momentum without extreme extension')
    elif 28 <= features.rsi_14 <= 48:
        bear += 1
        reasons.append('RSI supports bearish momentum without extreme extension')

    if features.rsi_14 > 78:
        bull = max(0, bull - 1)
        reasons.append('bullish score reduced for overextension')
    elif features.rsi_14 < 22:
        bear = max(0, bear - 1)
        reasons.append('bearish score reduced for overextension')

    if features.atr_14_pct < 0.03:
        bull = max(0, bull - 1)
        bear = max(0, bear - 1)
        reasons.append('very low volatility reduces trade quality')
    elif features.atr_14_pct > 1.25:
        bull = max(0, bull - 2)
        bear = max(0, bear - 2)
        reasons.append('extreme volatility reduces trade quality')

    return ScoreResult(bull_score=bull, bear_score=bear, reasons=reasons)
