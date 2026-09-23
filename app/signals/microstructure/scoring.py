from __future__ import annotations

from dataclasses import dataclass

from app.signals.microstructure.features import MicrostructureFeatureSnapshot


@dataclass(frozen=True)
class MicrostructureScoreResult:
    bull_score: int
    bear_score: int
    reasons: list[str]


def score_microstructure_features(features: MicrostructureFeatureSnapshot) -> MicrostructureScoreResult:
    bull = 0
    bear = 0
    reasons: list[str] = []

    # 1. Slow Regime Alignment (up to +2 points)
    if features.ema_fast > features.ema_slow and features.rsi_14 >= 48:
        bull += 2
        reasons.append('slow regime trend favors bullish continuation')
    elif features.ema_fast < features.ema_slow and features.rsi_14 <= 52:
        bear += 2
        reasons.append('slow regime trend favors bearish continuation')

    # 2. Fast Kinematics / Price Impulse (up to +3 points)
    if features.return_500ms_bps >= 1.0 and features.velocity_1s_bps >= 1.5:
        bull += 2
        reasons.append('strong positive 500ms/1s price velocity')
        if features.acceleration_1s_bps > 0.5:
            bull += 1
            reasons.append('positive price acceleration')
    elif features.return_500ms_bps <= -1.0 and features.velocity_1s_bps <= -1.5:
        bear += 2
        reasons.append('strong negative 500ms/1s price velocity')
        if features.acceleration_1s_bps < -0.5:
            bear += 1
            reasons.append('negative price acceleration')

    # 3. Order Book Imbalance (OBI_L5) & Microprice Deviation (up to +3 points)
    if features.obi_l5 >= 0.25:
        bull += 2
        reasons.append('order book depth favors buyers (OBI L5 >= 0.25)')
    elif features.obi_l5 <= -0.25:
        bear += 2
        reasons.append('order book depth favors sellers (OBI L5 <= -0.25)')

    if features.microprice_dev_bps >= 0.5:
        bull += 1
        reasons.append('microprice sits above mid price')
    elif features.microprice_dev_bps <= -0.5:
        bear += 1
        reasons.append('microprice sits below mid price')

    # 4. Aggressive Trade Flow Imbalance (TFI) (up to +2 points)
    if features.tfi_1s is not None and features.trade_count_1s >= 3:
        if features.tfi_1s >= 0.40:
            bull += 2
            reasons.append('recent 1s trade flow strongly favors buyers')
        elif features.tfi_1s <= -0.40:
            bear += 2
            reasons.append('recent 1s trade flow strongly favors sellers')
    elif features.tfi_5s is not None and features.trade_count_5s >= 5:
        if features.tfi_5s >= 0.35:
            bull += 1
            reasons.append('recent 5s trade flow favors buyers')
        elif features.tfi_5s <= -0.35:
            bear += 1
            reasons.append('recent 5s trade flow favors sellers')

    # 5. Overextension / Friction Reductions
    if features.rsi_14 > 80:
        bull = max(0, bull - 1)
        reasons.append('RSI extreme overbought reduces bull conviction')
    elif features.rsi_14 < 20:
        bear = max(0, bear - 1)
        reasons.append('RSI extreme oversold reduces bear conviction')

    if features.atr_14_pct < 0.02:
        bull = max(0, bull - 1)
        bear = max(0, bear - 1)
        reasons.append('low volatility reduces directional momentum potential')

    return MicrostructureScoreResult(bull_score=bull, bear_score=bear, reasons=reasons)
