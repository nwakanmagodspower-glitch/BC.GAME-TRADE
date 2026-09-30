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
) -> MicrostructureDecision:
    bull = score.bull_score
    bear = score.bear_score
    margin = abs(bull - bear)

    # Hard Vetoes
    if not is_fresh:
        return MicrostructureDecision(
            direction=SignalDirection.NO_TRADE,
            quality='UNAVAILABLE',
            bull_score=bull,
            bear_score=bear,
            margin=margin,
            reason='Microstructure data stream is stale or missing.',
        )

    # Order book checks only apply when evaluating external limit order books (not synthetic OTC feeds)
    if not is_synthetic:
        if features.spread_bps > max_spread_bps:
            return MicrostructureDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=bull,
                bear_score=bear,
                margin=margin,
                reason=f'Spread too wide ({features.spread_bps:.2f} bps > {max_spread_bps:.2f} bps).',
            )

        total_l5_depth = features.bid_depth_l5_qty + features.ask_depth_l5_qty
        if total_l5_depth < min_l5_volume:
            return MicrostructureDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=bull,
                bear_score=bear,
                margin=margin,
                reason=f'Order book depth too thin ({total_l5_depth:.4f} BTC < {min_l5_volume:.4f} BTC).',
            )

    # 5-Second Range Filters:
    # If trades are active (bar_5s_range > 0), filter flat chop and parabolic exhaustion traps
    if features.bar_5s_range > 0:
        if features.bar_5s_range < min_5s_range:
            return MicrostructureDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=bull,
                bear_score=bear,
                margin=margin,
                reason=f'5-second bar range is too narrow (${features.bar_5s_range:.2f} < ${min_5s_range:.2f}); high tie/noise risk (DeTrade awards ties to DOWN).',
            )
        if features.bar_5s_range > max_5s_range:
            return MicrostructureDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=bull,
                bear_score=bear,
                margin=margin,
                reason=f'5-second bar range is overextended (${features.bar_5s_range:.2f} > ${max_5s_range:.2f}); high retracement risk.',
            )

    # Parabolic Pre-Start Impulse / Exhaustion Gate (Synthetic OTC Defense)
    # When trading 5s rounds with a pre-start countdown, a large surge during the countdown
    # sets the Start Price at the peak of the impulse, creating extreme mean-reversion loss risk.
    if is_synthetic:
        if features.bar_5s_return > max_lead_impulse or (features.bar_5s_return >= 8.0 and features.bar_5s_rsi_14 > 70.0):
            return MicrostructureDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=bull,
                bear_score=bear,
                margin=margin,
                reason=f'Pre-start bullish impulse (+${features.bar_5s_return:.2f}) is overextended (exhaustion top). Buying UP risks an immediate 5-second retracement loss.',
            )
        if features.bar_5s_return < -max_lead_impulse or (features.bar_5s_return <= -8.0 and features.bar_5s_rsi_14 < 30.0):
            return MicrostructureDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=bull,
                bear_score=bear,
                margin=margin,
                reason=f'Pre-start bearish impulse (${features.bar_5s_return:.2f}) is deeply oversold (exhaustion bottom). Selling DOWN risks an immediate bounce.',
            )

    # Fast / Slow Conflict Veto (applies if slow regime or 5s micro-trend strongly conflicts)
    slow_bullish = (features.ema_fast > features.ema_slow) or (features.bar_5s_ema_fast > features.bar_5s_ema_slow and features.bar_5s_ema_fast > 0)
    slow_bearish = (features.ema_fast < features.ema_slow) or (features.bar_5s_ema_fast < features.bar_5s_ema_slow and features.bar_5s_ema_fast > 0)
    has_bearish_conflict = features.momentum_5m_pct < -0.10 or features.bar_5s_momentum_3bar < -2.0
    has_bullish_conflict = features.momentum_5m_pct > 0.10 or features.bar_5s_momentum_3bar > 2.0

    # Asymmetric Margin Requirement (DeTrade Tie-Rule Defense)
    # Under DeTrade rules, End <= Start awards the round to DOWN. UP has an inherent mathematical disadvantage.
    effective_up_margin = up_min_margin if up_min_margin is not None else (min_margin + 1 if is_synthetic else min_margin)

    # Decision logic
    if bull >= min_score and bull - bear >= effective_up_margin:
        if slow_bearish and has_bearish_conflict:
            return MicrostructureDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=bull,
                bear_score=bear,
                margin=margin,
                reason='Bullish fast microstructure conflicts strongly with bearish slow regime.',
            )

        if is_synthetic and features.bar_5s_return < 1.0:
            return MicrostructureDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=bull,
                bear_score=bear,
                margin=margin,
                reason='Bullish return is insufficient to overcome the house tie-loss edge.',
            )

        quality = 'STRONG' if bull >= 9 and margin >= 5 else 'VALID'
        return MicrostructureDecision(
            direction=SignalDirection.UP,
            quality=quality,
            bull_score=bull,
            bear_score=bear,
            margin=margin,
            reason='; '.join(score.reasons),
        )

    if bear >= min_score and bear - bull >= min_margin:
        if slow_bullish and has_bullish_conflict:
            return MicrostructureDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=bull,
                bear_score=bear,
                margin=margin,
                reason='Bearish fast microstructure conflicts strongly with bullish slow regime.',
            )

        quality = 'STRONG' if bear >= 9 and margin >= 5 else 'VALID'
        return MicrostructureDecision(
            direction=SignalDirection.DOWN,
            quality=quality,
            bull_score=bull,
            bear_score=bear,
            margin=margin,
            reason='; '.join(score.reasons),
        )

    return MicrostructureDecision(
        direction=SignalDirection.NO_TRADE,
        quality='NO_TRADE',
        bull_score=bull,
        bear_score=bear,
        margin=margin,
        reason='Microstructure directional evidence or margin is insufficient.',
    )
