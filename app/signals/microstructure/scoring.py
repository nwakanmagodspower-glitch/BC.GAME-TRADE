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
        # Calibrated on real DeTrade OTC micro-rounds: 10s synthetic momentum + 5s bar impulse.
        # Independent, additive scoring ensures valid moves are captured without artificial hurdles.

        # 1. 10-Second Synthetic Momentum (Core Engine, up to +3 points)
        eff_10s = features.delta_10s_usd if abs(features.delta_10s_usd) > 0.05 else features.bar_5s_return
        if eff_10s >= 2.0:
            bull += 3
            reasons.append(f'strong 10s synthetic momentum (+${eff_10s:.2f})')
        elif eff_10s >= 1.0:
            bull += 2
            reasons.append(f'10s synthetic momentum (+${eff_10s:.2f})')
        elif eff_10s >= 0.40:
            bull += 1
            reasons.append(f'positive 10s drift (+${eff_10s:.2f})')
        elif eff_10s <= -2.0:
            bear += 3
            reasons.append(f'strong 10s synthetic downward momentum (${eff_10s:.2f})')
        elif eff_10s <= -1.0:
            bear += 2
            reasons.append(f'10s synthetic downward momentum (${eff_10s:.2f})')
        elif eff_10s <= -0.40:
            bear += 1
            reasons.append(f'negative 10s drift (${eff_10s:.2f})')

        # 2. 5-Second Bar Impulse (up to +2 points)
        if features.bar_5s_return >= 1.0:
            bull += 2
            reasons.append(f'5s bar impulse expansion (+${features.bar_5s_return:.2f})')
        elif features.bar_5s_return >= 0.35:
            bull += 1
            reasons.append(f'5s bar positive impulse (+${features.bar_5s_return:.2f})')
        elif features.bar_5s_return <= -1.0:
            bear += 2
            reasons.append(f'5s bar impulse expansion (${features.bar_5s_return:.2f})')
        elif features.bar_5s_return <= -0.35:
            bear += 1
            reasons.append(f'5s bar downward impulse (${features.bar_5s_return:.2f})')

        # 3. 15-Second Multi-Bar Persistence (up to +2 points)
        if features.bar_5s_momentum_3bar >= 2.0:
            bull += 2
            reasons.append(f'15s persistent momentum (+${features.bar_5s_momentum_3bar:.2f})')
        elif features.bar_5s_momentum_3bar >= 0.8:
            bull += 1
            reasons.append(f'15s upward persistence (+${features.bar_5s_momentum_3bar:.2f})')
        elif features.bar_5s_momentum_3bar <= -2.0:
            bear += 2
            reasons.append(f'15s persistent downward momentum (${features.bar_5s_momentum_3bar:.2f})')
        elif features.bar_5s_momentum_3bar <= -0.8:
            bear += 1
            reasons.append(f'15s downward persistence (${features.bar_5s_momentum_3bar:.2f})')

        # 4. 30-Second Synthetic Drift (up to +2 points)
        eff_30s = features.delta_30s_usd if abs(features.delta_30s_usd) > 0.1 else (features.bar_5s_momentum_3bar * 2.0)
        if eff_30s >= 3.0:
            bull += 2
            reasons.append(f'30s synthetic upward drift (+${eff_30s:.2f})')
        elif eff_30s >= 1.5:
            bull += 1
            reasons.append(f'moderate 30s synthetic upward drift (+${eff_30s:.2f})')
        elif eff_30s <= -3.0:
            bear += 2
            reasons.append(f'30s synthetic downward drift (${eff_30s:.2f})')
        elif eff_30s <= -1.5:
            bear += 1
            reasons.append(f'moderate 30s synthetic downward drift (${eff_30s:.2f})')

        # 5. Taker Delta Flow Confirmation (+1 point)
        if features.bar_5s_taker_ratio >= 0.58:
            bull += 1
            reasons.append(f'buyer delta confirmed ({features.bar_5s_taker_ratio*100:.0f}%)')
        elif features.bar_5s_taker_ratio <= 0.42:
            bear += 1
            reasons.append(f'seller delta confirmed ({features.bar_5s_taker_ratio*100:.0f}%)')

        # 6. 5s Micro-Trend Alignment (EMA9 vs EMA21) (+1 point)
        if features.bar_5s_ema_fast > features.bar_5s_ema_slow and features.bar_5s_ema_fast > 0:
            bull += 1
            reasons.append('5s micro-trend (EMA9 > EMA21) confirms active bullish thrust')
        elif features.bar_5s_ema_fast < features.bar_5s_ema_slow and features.bar_5s_ema_fast > 0:
            bear += 1
            reasons.append('5s micro-trend (EMA9 < EMA21) confirms active bearish thrust')

        # 7. Fast Tick Kinematics (+1 point)
        if (features.delta_2s_usd >= 0.25 and features.delta_1s_usd >= 0.05) or (features.return_500ms_bps >= 0.4 and features.velocity_1s_bps >= 0.4):
            bull += 1
            reasons.append('positive tick kinematics aligned with upward thrust')
        elif (features.delta_2s_usd <= -0.25 and features.delta_1s_usd <= -0.05) or (features.return_500ms_bps <= -0.4 and features.velocity_1s_bps <= -0.4):
            bear += 1
            reasons.append('negative tick kinematics aligned with downward thrust')

        # 8. Counter-Jitter Defense (Sharp 2s reversal against trend)
        if features.delta_2s_usd < -0.60 and bull > 0:
            bull = max(0, bull - 2)
            reasons.append('sharp 2s counter-tick dampens UP signal')
        elif features.delta_2s_usd > 0.60 and bear > 0:
            bear = max(0, bear - 2)
            reasons.append('sharp 2s counter-tick dampens DOWN signal')

        # 9. Station Barrier Clearance ($50 Boundaries)
        if features.station_barrier_upper > 0 and features.station_barrier_dist_upper < 1.20 and bull > 0:
            bull = max(0, bull - 3)
            reasons.append(f'approaching $50 station ceiling (${features.station_barrier_dist_upper:.2f} away)')
        if features.station_barrier_lower > 0 and features.station_barrier_dist_lower < 1.20 and bear > 0:
            bear = max(0, bear - 3)
            reasons.append(f'approaching $50 station floor (${features.station_barrier_dist_lower:.2f} away)')

        # 10. Flat Chop Defense (BC.Game tie rule defense)
        eff_range = max(features.range_20s, features.lead_range_dollars, features.bar_5s_range)
        if eff_range < 0.60:
            bull = max(0, bull - 3)
            bear = max(0, bear - 3)
            reasons.append(f'flat volatility (${eff_range:.2f} < $0.60) risks house tie-loss')

        # 11. Station Regime Dynamics (Surge breakout & Bounded bounce)
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
