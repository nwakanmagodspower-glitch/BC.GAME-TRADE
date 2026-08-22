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

    The engine is precision-first: fast momentum and aggressor flow must agree.
    Slow candle indicators can confirm a setup, but cannot rescue contradictory
    or noisy five-second microstructure.
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

    # Aggressor flow. For a five-second contract this is required confirmation,
    # not merely a bonus.
    ratio = features.trade_buy_ratio
    if ratio is not None and features.trade_count_recent >= 12:
        if ratio >= 0.60:
            bull += 3; reasons.append('aggressive trade flow favors buyers')
        elif ratio <= 0.40:
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

    # Precision gates. A score is not enough: the setup must be coherent across
    # the 3s/5s horizons and supported by real aggressor flow.
    flow_bull = ratio is not None and ratio >= 0.55
    flow_bear = ratio is not None and ratio <= 0.45
    bull_aligned = (
        features.tick_return_3s_pct >= 0.006
        and features.tick_return_5s_pct >= 0.01
        and features.tick_return_1s_pct >= 0.0
        and flow_bull
    )
    bear_aligned = (
        features.tick_return_3s_pct <= -0.006
        and features.tick_return_5s_pct <= -0.01
        and features.tick_return_1s_pct <= 0.0
        and flow_bear
    )

    if not bull_aligned:
        bull = min(bull, 5)
        reasons.append('bull setup failed multi-horizon/flow confirmation')
    if not bear_aligned:
        bear = min(bear, 5)
        reasons.append('bear setup failed multi-horizon/flow confirmation')

    # A sharp one-second reversal against the 3s direction is a common late-entry
    # failure mode. Suppress that side entirely rather than chasing the move.
    if features.tick_return_1s_pct <= -0.002 and features.tick_return_3s_pct >= 0.006:
        bull = min(bull, 5)
        reasons.append('latest 1s move reversed against bullish setup')
    if features.tick_return_1s_pct >= 0.002 and features.tick_return_3s_pct <= -0.006:
        bear = min(bear, 5)
        reasons.append('latest 1s move reversed against bearish setup')

    # Reject unusually noisy microstructure. Five-second direction becomes much
    # less stable when tick-to-tick volatility dominates the directional move.
    if features.tick_volatility_5s_pct > 0.020:
        bull = min(bull, 5)
        bear = min(bear, 5)
        reasons.append('micro volatility too high for precision entry')

    # Do not take a five-second trade directly against both slow-context checks.
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
