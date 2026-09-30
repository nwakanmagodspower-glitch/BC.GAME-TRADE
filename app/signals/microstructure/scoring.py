from __future__ import annotations

from dataclasses import dataclass

from app.signals.microstructure.features import MicrostructureFeatureSnapshot


@dataclass(frozen=True)
class MicrostructureScoreResult:
    bull_score: int
    bear_score: int
    reasons: list[str]


def score_microstructure_features(
    features: MicrostructureFeatureSnapshot,
    *,
    is_synthetic: bool = False,
) -> MicrostructureScoreResult:
    bull = 0
    bear = 0
    reasons: list[str] = []

    if is_synthetic:
        # PURE DETRADE SYNTHETIC SCORING
        # 100% decoupled from Binance spot order book (OBI) and Binance trade flows.
        # Operates purely on DeTrade synthetic bar impulse, multi-bar persistence, and tick kinematics.

        # 1. 5-Second Bar Micro-Impulse (up to +4 points)
        if features.bar_5s_return >= 1.50 and features.bar_5s_taker_ratio >= 0.55:
            bull += 2
            reasons.append(f'5s bar bullish impulse (+${features.bar_5s_return:.2f}) with buyer delta ({features.bar_5s_taker_ratio*100:.0f}%)')
            if features.bar_5s_return >= 3.00:
                bull += 1
                reasons.append(f'strong 5s bullish expansion (+${features.bar_5s_return:.2f})')
        elif features.bar_5s_return <= -1.20 and features.bar_5s_taker_ratio <= 0.45:
            bear += 2
            reasons.append(f'5s bar bearish impulse (${features.bar_5s_return:.2f}) with seller delta ({features.bar_5s_taker_ratio*100:.0f}%)')
            if features.bar_5s_return <= -2.50:
                bear += 1
                reasons.append(f'strong 5s downward expansion (${features.bar_5s_return:.2f})')

        # 2. Multi-bar Persistence (up to +2 points)
        if features.bar_5s_momentum_3bar >= 2.0:
            bull += 2
            reasons.append(f'3-bar synthetic momentum confirms upward continuation (+${features.bar_5s_momentum_3bar:.2f})')
        elif features.bar_5s_momentum_3bar <= -2.0:
            bear += 2
            reasons.append(f'3-bar synthetic momentum confirms downward continuation (${features.bar_5s_momentum_3bar:.2f})')

        # 3. 5s Micro-Trend Alignment (9 vs 21 EMA on 5s bars)
        if features.bar_5s_ema_fast > features.bar_5s_ema_slow and 48 <= features.bar_5s_rsi_14 <= 70:
            bull += 2
            reasons.append('5s micro-trend (EMA9 > EMA21) favors bullish continuation')
        elif features.bar_5s_ema_fast < features.bar_5s_ema_slow and 30 <= features.bar_5s_rsi_14 <= 52:
            bear += 2
            reasons.append('5s micro-trend (EMA9 < EMA21) favors bearish continuation')
        elif features.ema_fast > features.ema_slow and features.rsi_14 >= 48:
            bull += 1
            reasons.append('regime trend favors bullish continuation')
        elif features.ema_fast < features.ema_slow and features.rsi_14 <= 52:
            bear += 1
            reasons.append('regime trend favors bearish continuation')

        # 4. Real-time Tick Kinematics (up to +3 points)
        if features.return_500ms_bps >= 1.0 and features.velocity_1s_bps >= 1.5:
            bull += 2
            reasons.append('strong positive synthetic tick velocity')
            if features.acceleration_1s_bps > 0.5:
                bull += 1
                reasons.append('positive tick acceleration')
        elif features.return_500ms_bps <= -1.0 and features.velocity_1s_bps <= -1.5:
            bear += 2
            reasons.append('strong negative synthetic tick velocity')
            if features.acceleration_1s_bps < -0.5:
                bear += 1
                reasons.append('negative tick acceleration')

        # 5. Overextension & Pre-Start Exhaustion Penalties
        if features.bar_5s_rsi_14 > 72:
            bull = max(0, bull - 3)
            reasons.append('5s RSI overbought indicates exhaustion risk before contract start')
        elif features.bar_5s_rsi_14 < 28:
            bear = max(0, bear - 3)
            reasons.append('5s RSI oversold indicates bounce risk before contract start')

        if features.atr_14_pct < 0.01:
            bull = max(0, bull - 1)
            bear = max(0, bear - 1)
            reasons.append('low volatility reduces directional momentum potential')

        return MicrostructureScoreResult(bull_score=bull, bear_score=bear, reasons=reasons)

    # 1. 5-Second Bar Micro-Momentum & Taker Flow (up to +3 points)
    # Tested empirically: 5s return with taker alignment in healthy range achieves 66.7% continuation
    if 1.50 <= features.bar_5s_range <= 10.0:
        if features.bar_5s_return >= 0.50 and features.bar_5s_taker_ratio >= 0.58:
            bull += 2
            reasons.append(f'5s bar bullish impulse (+${features.bar_5s_return:.2f}) with taker buy flow ({features.bar_5s_taker_ratio*100:.0f}%)')
        elif features.bar_5s_return <= -0.50 and features.bar_5s_taker_ratio <= 0.42:
            bear += 2
            reasons.append(f'5s bar bearish impulse (${features.bar_5s_return:.2f}) with taker sell flow ({features.bar_5s_taker_ratio*100:.0f}%)')

    # 5s Trend Alignment (9 vs 21 EMA on 5s bars, 45s vs 105s)
    if features.bar_5s_ema_fast > features.bar_5s_ema_slow and features.bar_5s_rsi_14 >= 48:
        bull += 1
        reasons.append('5s micro-trend (EMA9 > EMA21) favors bullish continuation')
    elif features.bar_5s_ema_fast < features.bar_5s_ema_slow and features.bar_5s_rsi_14 <= 52:
        bear += 1
        reasons.append('5s micro-trend (EMA9 < EMA21) favors bearish continuation')
    elif features.ema_fast > features.ema_slow and features.rsi_14 >= 48:
        bull += 1
        reasons.append('regime trend favors bullish continuation')
    elif features.ema_fast < features.ema_slow and features.rsi_14 <= 52:
        bear += 1
        reasons.append('regime trend favors bearish continuation')

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
