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
        # Driven by multi-bar synthetic drift (30s) and 10s intermediate confirmation.
        # Empirically validated on real DeTrade settlement rounds (61.5% - 66.7% win rate).

        # 1. 30-Second Synthetic Drift (Core Engine, up to +4 points)
        eff_30s = features.delta_30s_usd if abs(features.delta_30s_usd) > 0.1 else (features.bar_5s_momentum_3bar * 2.0)
        if eff_30s >= 6.0:
            bull += 4
            reasons.append(f'30s synthetic upward drift (+${eff_30s:.2f})')
        elif eff_30s >= 4.0:
            bull += 3
            reasons.append(f'moderate 30s synthetic upward drift (+${eff_30s:.2f})')
        elif eff_30s <= -6.0:
            bear += 4
            reasons.append(f'30s synthetic downward drift (${eff_30s:.2f})')
        elif eff_30s <= -4.0:
            bear += 3
            reasons.append(f'moderate 30s synthetic downward drift (${eff_30s:.2f})')

        # 2. 10-Second Intermediate Trend Alignment (up to +2 points / -3 penalty)
        eff_10s = features.delta_10s_usd if abs(features.delta_10s_usd) > 0.1 else features.bar_5s_return
        if eff_10s >= 0.5 and bull > 0:
            bull += 2
            reasons.append(f'10s intermediate momentum aligned (+${eff_10s:.2f})')
        elif eff_10s <= -0.5 and bear > 0:
            bear += 2
            reasons.append(f'10s intermediate momentum aligned (${eff_10s:.2f})')
        elif eff_10s < -0.5 and bull > 0:
            bull = max(0, bull - 3)
            reasons.append(f'10s counter-pullback (${eff_10s:.2f}) weakens upward drift')
        elif eff_10s > 0.5 and bear > 0:
            bear = max(0, bear - 3)
            reasons.append(f'10s counter-bounce (+${eff_10s:.2f}) weakens downward drift')

        # 3. 5-Second Bar Expansion & Taker Flow Confirmation (up to +2 points)
        if features.bar_5s_return >= 2.0 and bull > 0:
            bull += 1
            reasons.append(f'strong 5s bullish expansion (+${features.bar_5s_return:.2f})')
        elif features.bar_5s_return <= -2.0 and bear > 0:
            bear += 1
            reasons.append(f'strong 5s downward expansion (${features.bar_5s_return:.2f})')

        if features.bar_5s_taker_ratio >= 0.58 and bull > 0:
            bull += 1
            reasons.append(f'buyer delta confirmed ({features.bar_5s_taker_ratio*100:.0f}%)')
        elif features.bar_5s_taker_ratio <= 0.42 and bear > 0:
            bear += 1
            reasons.append(f'seller delta confirmed ({features.bar_5s_taker_ratio*100:.0f}%)')

        # 4. Micro-Trend & Kinematics Confirmation (up to +2 points)
        if features.bar_5s_ema_fast > features.bar_5s_ema_slow and bull > 0 and features.delta_2s_usd >= 0.0:
            bull += 1
            reasons.append('5s micro-trend (EMA9 > EMA21) confirms active bullish thrust')
        elif features.bar_5s_ema_fast < features.bar_5s_ema_slow and bear > 0 and features.delta_2s_usd <= 0.0:
            bear += 1
            reasons.append('5s micro-trend (EMA9 < EMA21) confirms active bearish thrust')

        if (features.delta_2s_usd >= 0.35 and features.delta_1s_usd >= 0.15) or (features.return_500ms_bps >= 0.5 and features.velocity_1s_bps >= 0.6):
            if bull > 0:
                bull += 1
                reasons.append('positive tick kinematics aligned with upward drift')
        elif (features.delta_2s_usd <= -0.35 and features.delta_1s_usd <= -0.15) or (features.return_500ms_bps <= -0.5 and features.velocity_1s_bps <= -0.6):
            if bear > 0:
                bear += 1
                reasons.append('negative tick kinematics aligned with downward drift')

        # 5. Late Jitter Defense (Last 2s must not violently contradict)
        if features.delta_2s_usd < -0.3 and bull > 0:
            bull = max(0, bull - 2)
            reasons.append('2s counter-tick dampens UP signal')
        elif features.delta_2s_usd > 0.3 and bear > 0:
            bear = max(0, bear - 2)
            reasons.append('2s counter-tick dampens DOWN signal')

        # 6. Station Barrier Clearance ($50 Boundaries)
        if features.station_barrier_upper > 0 and features.station_barrier_dist_upper < 2.0 and bull > 0:
            bull = max(0, bull - 3)
            reasons.append(f'approaching $50 station ceiling (${features.station_barrier_dist_upper:.2f} away)')
        if features.station_barrier_lower > 0 and features.station_barrier_dist_lower < 2.0 and bear > 0:
            bear = max(0, bear - 3)
            reasons.append(f'approaching $50 station floor (${features.station_barrier_dist_lower:.2f} away)')

        # 7. Volatility Floor (BC.Game tie rule defense)
        eff_range = max(features.range_20s, features.lead_range_dollars, features.bar_5s_range)
        if eff_range < 2.0:
            bull = max(0, bull - 4)
            bear = max(0, bear - 4)
            reasons.append(f'low 20s volatility (${eff_range:.2f} < $2.00) risks house tie-loss')

        # 8. Station Regime Dynamics (Surge breakout & Bounded bounce)
        if features.regime_classification == 'SURGE_BREAKOUT':
            if features.delta_2s_usd > 0:
                bull += 2
                reasons.append(f'station breakout surge confirmed (+${features.delta_2s_usd:.2f})')
            elif features.delta_2s_usd < 0:
                bear += 2
                reasons.append(f'station breakdown surge confirmed (${features.delta_2s_usd:.2f})')
        elif features.regime_classification == 'BOUNDED_BOUNCE':
            if features.station_nearest_barrier_type == 'UPPER':
                bear += 2
                reasons.append(f'bounded bounce off upper station barrier (${features.station_barrier_upper:.0f})')
            elif features.station_nearest_barrier_type == 'LOWER':
                bull += 2
                reasons.append(f'bounded bounce off lower station barrier (${features.station_barrier_lower:.0f})')

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
