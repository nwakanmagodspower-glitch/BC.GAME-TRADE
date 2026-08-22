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

    Precision-first rules: fast momentum and aggressor flow must agree. Slow
    candle context may confirm a setup, but cannot rescue contradictory/noisy
    microstructure.
    """
    bull = 0
    bear = 0
    reasons: list[str] = []

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

    ratio = features.trade_buy_ratio
    if ratio is not None and features.trade_count_recent >= 12:
        if ratio >= 0.60:
            bull += 3; reasons.append('aggressive trade flow favors buyers')
        elif ratio <= 0.40:
            bear += 3; reasons.append('aggressive trade flow favors sellers')

    if features.ema_fast > features.ema_slow:
        bull += 1; reasons.append('short trend context bullish')
    elif features.ema_fast < features.ema_slow:
        bear += 1; reasons.append('short trend context bearish')

    if features.structure == 'BULLISH':
        bull += 1; reasons.append('market structure context bullish')
    elif features.structure == 'BEARISH':
        bear += 1; reasons.append('market structure context bearish')

    # Hard confirmation: all fast horizons must point the same way and actual
    # taker flow must be decisively one-sided. Neutral 55/45 flow is no longer
    # enough to qualify a five-second signal.
    flow_bull = ratio is not None and ratio >= 0.60
    flow_bear = ratio is not None and ratio <= 0.40
    bull_aligned = (
        features.tick_return_1s_pct >= 0.001
        and features.tick_return_3s_pct >= 0.006
        and features.tick_return_5s_pct >= 0.01
        and flow_bull
    )
    bear_aligned = (
        features.tick_return_1s_pct <= -0.001
        and features.tick_return_3s_pct <= -0.006
        and features.tick_return_5s_pct <= -0.01
        and flow_bear
    )

    if not bull_aligned:
        bull = min(bull, 5)
        reasons.append('bull setup failed multi-horizon/flow confirmation')
    if not bear_aligned:
        bear = min(bear, 5)
        reasons.append('bear setup failed multi-horizon/flow confirmation')

    if features.tick_return_1s_pct <= -0.002 and features.tick_return_3s_pct >= 0.006:
        bull = min(bull, 5)
        reasons.append('latest 1s move reversed against bullish setup')
    if features.tick_return_1s_pct >= 0.002 and features.tick_return_3s_pct <= -0.006:
        bear = min(bear, 5)
        reasons.append('latest 1s move reversed against bearish setup')

    if features.tick_volatility_5s_pct > 0.020:
        bull = min(bull, 5)
        bear = min(bear, 5)
        reasons.append('micro volatility too high for precision entry')

    if features.ema_fast < features.ema_slow and features.structure == 'BEARISH':
        bull = min(bull, 5)
        reasons.append('bull setup conflicts with trend and structure')
    if features.ema_fast > features.ema_slow and features.structure == 'BULLISH':
        bear = min(bear, 5)
        reasons.append('bear setup conflicts with trend and structure')

    if features.trade_count_recent < 12:
        bull = min(bull, 5)
        bear = min(bear, 5)
        reasons.append('insufficient recent trades')

    if abs(features.tick_return_3s_pct) < 0.004 or abs(features.tick_return_5s_pct) < 0.007:
        bull = min(bull, 5)
        bear = min(bear, 5)
        reasons.append('micro direction too weak')

    return ScoreResult(bull_score=bull, bear_score=bear, reasons=reasons)
