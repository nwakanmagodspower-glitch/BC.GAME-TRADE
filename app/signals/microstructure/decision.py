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
                reason=f'5-second bar range is too narrow (${features.bar_5s_range:.2f} < ${min_5s_range:.2f}); high tie/noise risk.',
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

    # Fast / Slow Conflict Veto (applies if slow regime or 5s micro-trend strongly conflicts)
    slow_bullish = (features.ema_fast > features.ema_slow) or (features.bar_5s_ema_fast > features.bar_5s_ema_slow and features.bar_5s_ema_fast > 0)
    slow_bearish = (features.ema_fast < features.ema_slow) or (features.bar_5s_ema_fast < features.bar_5s_ema_slow and features.bar_5s_ema_fast > 0)
    has_bearish_conflict = features.momentum_5m_pct < -0.10 or features.bar_5s_momentum_3bar < -2.0
    has_bullish_conflict = features.momentum_5m_pct > 0.10 or features.bar_5s_momentum_3bar > 2.0

    # Decision logic
    if bull >= min_score and bull - bear >= min_margin:
        if slow_bearish and has_bearish_conflict:
            return MicrostructureDecision(
                direction=SignalDirection.NO_TRADE,
                quality='NO_TRADE',
                bull_score=bull,
                bear_score=bear,
                margin=margin,
                reason='Bullish fast microstructure conflicts strongly with bearish slow regime.',
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
