from __future__ import annotations

from dataclasses import dataclass

from app.signals.features import FeatureSnapshot


@dataclass(frozen=True)
class ScoreResult:
    bull_score: int
    bear_score: int
    reasons: list[str]


def score_features(features: FeatureSnapshot) -> ScoreResult:
    """Score immediate BTC direction for a five-second target.

    Tick velocity/trade flow are primary. Slower candle indicators are context
    only and cannot create a directional signal by themselves.
    """
    bull = 0
    bear = 0
    reasons: list[str] = []

    # Primary micro-momentum.
    if features.tick_return_1s_pct >= 0.003:
        bull += 3; reasons.append('1s price impulse up')
    elif features.tick_return_1s_pct <= -0.003:
        bear += 3; reasons.append('1s price impulse down')

    if features.tick_return_3s_pct >= 0.006:
        bull += 3; reasons.append('3s micro momentum up')
    elif features.tick_return_3s_pct <= -0.006:
        bear += 3; reasons.append('3s micro momentum down')

    if features.tick_return_5s_pct >= 0.01:
        bull += 2; reasons.append('5s directional persistence up')
    elif features.tick_return_5s_pct <= -0.01:
        bear += 2; reasons.append('5s directional persistence down')

    if features.tick_acceleration_pct >= 0.002:
        bull += 1; reasons.append('upward micro acceleration')
    elif features.tick_acceleration_pct <= -0.002:
        bear += 1; reasons.append('downward micro acceleration')

    # Aggressor flow.
    if features.trade_buy_ratio is not None and features.trade_count_recent >= 12:
        if features.trade_buy_ratio >= 0.60:
            bull += 3; reasons.append('aggressive trade flow favors buyers')
        elif features.trade_buy_ratio <= 0.40:
            bear += 3; reasons.append('aggressive trade flow favors sellers')

    # Slow context; intentionally small weight.
    if features.ema_fast > features.ema_slow:
        bull += 1; reasons.append('short trend context bullish')
    elif features.ema_fast < features.ema_slow:
        bear += 1; reasons.append('short trend context bearish')

    if features.structure == 'BULLISH':
        bull += 1; reasons.append('market structure context bullish')
    elif features.structure == 'BEARISH':
        bear += 1; reasons.append('market structure context bearish')

    # Penalize thin/noisy microstructure. Thresholds are research defaults and
    # require forward calibration against actual BC.GAME round labels.
    if features.trade_count_recent < 8:
        bull = max(0, bull - 2); bear = max(0, bear - 2)
        reasons.append('insufficient recent trades')
    if features.tick_volatility_5s_pct > 0.025:
        bull = max(0, bull - 2); bear = max(0, bear - 2)
        reasons.append('micro volatility too high')
    if abs(features.tick_return_3s_pct) < 0.002 and abs(features.tick_return_5s_pct) < 0.004:
        bull = max(0, bull - 2); bear = max(0, bear - 2)
        reasons.append('micro direction too weak')

    return ScoreResult(bull_score=bull, bear_score=bear, reasons=reasons)
