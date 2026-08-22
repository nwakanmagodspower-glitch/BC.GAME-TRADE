from __future__ import annotations

from dataclasses import dataclass

from app.signals.features import FeatureSnapshot


@dataclass(frozen=True)
class ScoreResult:
    bull_score: int
    bear_score: int
    reasons: list[str]


def score_features(features: FeatureSnapshot) -> ScoreResult:
    """Score immediate BTC direction for the five-second target.

    V1.4.2 keeps fast momentum as the primary evidence, but does not hard-fail a
    setup merely because Binance aggressor flow is neutral. Flow remains useful
    evidence and the cross-venue layer later supplies an independent confirmation.
    Hard caps are reserved for genuinely contradictory/reversing/noisy structure.
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
        elif ratio >= 0.54:
            bull += 1; reasons.append('trade flow modestly favors buyers')
        elif ratio <= 0.46:
            bear += 1; reasons.append('trade flow modestly favors sellers')

    if features.ema_fast > features.ema_slow:
        bull += 1; reasons.append('short trend context bullish')
    elif features.ema_fast < features.ema_slow:
        bear += 1; reasons.append('short trend context bearish')

    if features.structure == 'BULLISH':
        bull += 1; reasons.append('market structure context bullish')
    elif features.structure == 'BEARISH':
        bear += 1; reasons.append('market structure context bearish')

    # The 3s and 5s windows define persistence. Neutral Binance flow no longer
    # destroys the score here; independent Binance/Bybit confirmation is applied
    # later. This fixes the old double-gating that could make signals impossible.
    bull_persistent = (
        features.tick_return_3s_pct >= 0.004
        and features.tick_return_5s_pct >= 0.007
    )
    bear_persistent = (
        features.tick_return_3s_pct <= -0.004
        and features.tick_return_5s_pct <= -0.007
    )
    if not bull_persistent:
        bull = min(bull, 6)
        reasons.append('bull setup lacks 3s/5s persistence')
    if not bear_persistent:
        bear = min(bear, 6)
        reasons.append('bear setup lacks 3s/5s persistence')

    # A clear newest-second reversal is still a genuine veto for that direction.
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

    # Strong disagreement between slow context and the proposed direction is a
    # warning, not a universal blocker. It trims the score rather than erasing it.
    if features.ema_fast < features.ema_slow and features.structure == 'BEARISH':
        bull = max(0, bull - 2)
        reasons.append('bull setup conflicts with bearish trend context')
    if features.ema_fast > features.ema_slow and features.structure == 'BULLISH':
        bear = max(0, bear - 2)
        reasons.append('bear setup conflicts with bullish trend context')

    if features.trade_count_recent < 12:
        bull = min(bull, 5)
        bear = min(bear, 5)
        reasons.append('insufficient recent trades')

    # Only suppress both sides when BOTH persistence windows are weak. The old
    # OR condition rejected a setup whenever either one window was quiet.
    if abs(features.tick_return_3s_pct) < 0.004 and abs(features.tick_return_5s_pct) < 0.007:
        bull = min(bull, 5)
        bear = min(bear, 5)
        reasons.append('micro direction too weak')

    return ScoreResult(bull_score=bull, bear_score=bear, reasons=reasons)
