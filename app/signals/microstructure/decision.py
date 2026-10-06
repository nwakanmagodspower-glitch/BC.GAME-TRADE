from __future__ import annotations

from dataclasses import dataclass

from app.models.entities import SignalDirection
from app.signals.microstructure.features import MicrostructureFeatureSnapshot
from app.signals.microstructure.scoring import MicrostructureScoreResult


@dataclass(frozen=True)
class MicrostructureDecision:
    direction: SignalDirection
    quality: str
    bull_score: int
    bear_score: int
    margin: int
    reason: str
    stake_tier: str = 'DEFENSIVE'
    stake_recommendation: str = '🛡️ PRESERVE CAPITAL (Skip round — wait for Prime)'


def decide_microstructure(
    score: MicrostructureScoreResult,
    features: MicrostructureFeatureSnapshot,
    is_fresh: bool = True,
    max_spread_bps: float = 3.0,
    min_l5_volume: float = 0.05,
    min_score: int = 7,
    min_margin: int = 4,
    min_5s_range: float = 1.0,
    max_5s_range: float = 12.0,
    *,
    is_synthetic: bool = False,
    up_min_margin: int | None = None,
    max_lead_impulse: float = 16.0,
    seconds_until_start: float | None = None,
) -> MicrostructureDecision:
    bull = score.bull_score
    bear = score.bear_score
    margin = abs(bull - bear)

    def _make(dir_val: SignalDirection, qual_val: str, reason_val: str) -> MicrostructureDecision:
        if dir_val != SignalDirection.NO_TRADE:
            peak = max(bull, bear)
            if qual_val == 'STRONG' or (peak >= 8 and margin >= 5):
                tier = 'PRIME'
                rec = '🔥 Stake High'
            else:
                tier = 'STANDARD'
                rec = '⚡ Stake Low'
        else:
            tier = 'DEFENSIVE'
            rec = '🛡️ Skip Round'
        return MicrostructureDecision(
            direction=dir_val,
            quality=qual_val,
            bull_score=bull,
            bear_score=bear,
            margin=margin,
            reason=reason_val,
            stake_tier=tier,
            stake_recommendation=rec,
        )

    # Execution countdown gate: only veto if the round has already started (<= 0.0s)
    if seconds_until_start is not None and seconds_until_start <= 0.0:
        return _make(
            SignalDirection.NO_TRADE,
            'NO_TRADE',
            'This round has already started. Wait for the new countdown and tap Scan.',
        )

    # Hard Vetoes
    if not is_fresh:
        return _make(
            SignalDirection.NO_TRADE,
            'UNAVAILABLE',
            'Microstructure data stream is stale or missing.',
        )

    # Order book checks only apply when evaluating external limit order books (not synthetic OTC feeds)
    if not is_synthetic:
        if features.spread_bps > max_spread_bps:
            return _make(
                SignalDirection.NO_TRADE,
                'NO_TRADE',
                f'Spread too wide ({features.spread_bps:.2f} bps > {max_spread_bps:.2f} bps).',
            )

        total_l5_depth = features.bid_depth_l5_qty + features.ask_depth_l5_qty
        if total_l5_depth < min_l5_volume:
            return _make(
                SignalDirection.NO_TRADE,
                'NO_TRADE',
                f'Order book depth too thin ({total_l5_depth:.4f} BTC < {min_l5_volume:.4f} BTC).',
            )

    # 5-Second Range Filters:
    # Filter flat chop and parabolic exhaustion traps
    # 5-Second Range Filters:
    # Filter flat chop and parabolic exhaustion traps
    if is_synthetic:
        eff_range = max(features.range_20s, features.lead_range_dollars, features.bar_5s_range)
        eff_min = min_5s_range if min_5s_range is not None else 0.80
        if eff_range < eff_min:
            return _make(
                SignalDirection.NO_TRADE,
                'NO_TRADE',
                f'20-second range is too narrow (${eff_range:.2f} < ${eff_min:.2f}); market in flat chop risks BC.Game tie-loss.',
            )
        if eff_range > 35.0:
            return _make(
                SignalDirection.NO_TRADE,
                'NO_TRADE',
                f'20-second range is anomalous (${eff_range:.2f} > $35.00); extreme volatility risk.',
            )
    elif features.bar_5s_range > 0:
        if features.bar_5s_range < min_5s_range:
            return _make(
                SignalDirection.NO_TRADE,
                'NO_TRADE',
                f'5-second bar range is too narrow (${features.bar_5s_range:.2f} < ${min_5s_range:.2f}); high tie/noise risk (DeTrade awards ties to DOWN).',
            )
        if features.bar_5s_range > max_5s_range:
            return _make(
                SignalDirection.NO_TRADE,
                'NO_TRADE',
                f'5-second bar range is overextended (${features.bar_5s_range:.2f} > ${max_5s_range:.2f}); high retracement risk.',
            )

    # Parabolic Pre-Start Impulse / Exhaustion Gate (Synthetic OTC Defense)
    if is_synthetic:
        if features.delta_5s_usd > 12.0 or features.bar_5s_return > 12.0:
            return _make(
                SignalDirection.NO_TRADE,
                'NO_TRADE',
                'Pre-start 5s impulse is overextended (exhaustion top). Buying UP risks an immediate retracement loss.',
            )
        if features.delta_5s_usd < -12.0 or features.bar_5s_return < -12.0:
            return _make(
                SignalDirection.NO_TRADE,
                'NO_TRADE',
                'Pre-start 5s impulse is deeply oversold (exhaustion bottom). Selling DOWN risks an immediate bounce.',
            )

    # Fast / Slow Conflict Veto (applies if slow regime or 5s micro-trend strongly conflicts)
    slow_bullish = (features.ema_fast > features.ema_slow) or (features.bar_5s_ema_fast > features.bar_5s_ema_slow and features.bar_5s_ema_fast > 0)
    slow_bearish = (features.ema_fast < features.ema_slow) or (features.bar_5s_ema_fast < features.bar_5s_ema_slow and features.bar_5s_ema_fast > 0)
    has_bearish_conflict = features.momentum_5m_pct < -0.10 or features.bar_5s_momentum_3bar < -2.0
    has_bullish_conflict = features.momentum_5m_pct > 0.10 or features.bar_5s_momentum_3bar > 2.0

    # 1-Minute Trend Harmony Gate (Regime Context)
    trend_strongly_bearish = (features.ema_fast < features.ema_slow and features.rsi_14 < 44.0) or features.momentum_5m_pct < -0.08
    trend_strongly_bullish = (features.ema_fast > features.ema_slow and features.rsi_14 > 56.0) or features.momentum_5m_pct > 0.08

    # Asymmetric Margin Requirement (DeTrade Tie-Rule Defense)
    # Under DeTrade rules, End <= Start awards the round to DOWN. UP has an inherent mathematical disadvantage.
    effective_up_margin = up_min_margin if up_min_margin is not None else (min_margin + 1 if is_synthetic else min_margin)

    # Decision logic
    if bull >= min_score and bull - bear >= effective_up_margin:
        if (slow_bearish and has_bearish_conflict) or trend_strongly_bearish:
            return _make(
                SignalDirection.NO_TRADE,
                'NO_TRADE',
                'Bullish fast microstructure conflicts strongly with broader bearish trend. Preserving capital against trend cascade.',
            )

        if is_synthetic:
            if features.regime_classification == 'BOUNDED_BOUNCE' and features.station_nearest_barrier_type == 'UPPER':
                return _make(
                    SignalDirection.NO_TRADE,
                    'NO_TRADE',
                    f'Station ceiling barrier (${features.station_barrier_upper:.0f}) rejection; bounded bounce vetoes UP.',
                )
            if features.station_barrier_upper > 0 and features.station_barrier_dist_upper < 1.00:
                return _make(
                    SignalDirection.NO_TRADE,
                    'NO_TRADE',
                    f'Price is within ${features.station_barrier_dist_upper:.2f} of $50 station ceiling. Skipping UP to avoid barrier rejection.',
                )
            if features.bar_5s_return < 0.60 and features.delta_30s_usd < 3.0:
                return _make(
                    SignalDirection.NO_TRADE,
                    'NO_TRADE',
                    f'Bullish return (+${features.bar_5s_return:.2f}) is insufficient to overcome the BC.Game tie-loss house edge.',
                )
            if (
                features.delta_1s_usd < -0.20
                or features.delta_2s_usd < -0.30
                or features.velocity_1s_bps < -0.30
                or features.internal_velocity_usd < -0.30
            ):
                return _make(
                    SignalDirection.NO_TRADE,
                    'NO_TRADE',
                    'Price is actively ticking down; entering UP risks immediate adverse movement.',
                )

        quality = 'STRONG' if (bull >= 6 and margin >= 3) or features.delta_10s_usd >= 1.5 or features.regime_classification == 'SURGE_BREAKOUT' else 'VALID'
        return _make(
            SignalDirection.UP,
            quality,
            '; '.join(score.reasons),
        )

    if bear >= min_score and bear - bull >= min_margin:
        if (slow_bullish and has_bullish_conflict) or trend_strongly_bullish:
            return _make(
                SignalDirection.NO_TRADE,
                'NO_TRADE',
                'Bearish fast microstructure conflicts strongly with broader bullish trend. Preserving capital against trend continuation.',
            )

        if is_synthetic:
            if features.regime_classification == 'BOUNDED_BOUNCE' and features.station_nearest_barrier_type == 'LOWER':
                return _make(
                    SignalDirection.NO_TRADE,
                    'NO_TRADE',
                    f'Station floor barrier (${features.station_barrier_lower:.0f}) rejection; bounded bounce vetoes DOWN.',
                )
            if features.station_barrier_lower > 0 and features.station_barrier_dist_lower < 1.00:
                return _make(
                    SignalDirection.NO_TRADE,
                    'NO_TRADE',
                    f'Price is within ${features.station_barrier_dist_lower:.2f} of $50 station floor. Skipping DOWN to avoid barrier bounce.',
                )
            if features.bar_5s_return > -0.60 and features.delta_30s_usd > -3.0:
                return _make(
                    SignalDirection.NO_TRADE,
                    'NO_TRADE',
                    f'Bearish return (${features.bar_5s_return:.2f}) is insufficient to confirm downward continuation.',
                )
            if (
                features.delta_1s_usd > 0.20
                or features.delta_2s_usd > 0.30
                or features.velocity_1s_bps > 0.30
                or features.internal_velocity_usd > 0.30
            ):
                return _make(
                    SignalDirection.NO_TRADE,
                    'NO_TRADE',
                    'Price is actively ticking up; entering DOWN risks adverse upward breakout.',
                )

        quality = 'STRONG' if (bear >= 6 and margin >= 3) or features.delta_10s_usd <= -1.5 or features.regime_classification == 'SURGE_BREAKOUT' else 'VALID'
        return _make(
            SignalDirection.DOWN,
            quality,
            '; '.join(score.reasons),
        )

    return _make(
        SignalDirection.NO_TRADE,
        'NO_TRADE',
        'Microstructure directional evidence or margin is insufficient.',
    )
