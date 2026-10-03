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
    # If trades are active (bar_5s_range > 0), filter flat chop and parabolic exhaustion traps
    if features.bar_5s_range > 0:
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
    # When trading 5s rounds with a pre-start countdown, a large surge during the countdown
    # sets the Start Price at the peak of the impulse, creating extreme mean-reversion loss risk.
    if is_synthetic:
        if features.bar_5s_return > max_lead_impulse or (features.bar_5s_return >= 8.0 and features.bar_5s_rsi_14 > 70.0):
            return _make(
                SignalDirection.NO_TRADE,
                'NO_TRADE',
                f'Pre-start bullish impulse (+${features.bar_5s_return:.2f}) is overextended (exhaustion top). Buying UP risks an immediate 5-second retracement loss.',
            )
        if features.bar_5s_return < -max_lead_impulse or (features.bar_5s_return <= -8.0 and features.bar_5s_rsi_14 < 30.0):
            return _make(
                SignalDirection.NO_TRADE,
                'NO_TRADE',
                f'Pre-start bearish impulse (${features.bar_5s_return:.2f}) is deeply oversold (exhaustion bottom). Selling DOWN risks an immediate bounce.',
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
            if features.bar_5s_return < 1.00:
                return _make(
                    SignalDirection.NO_TRADE,
                    'NO_TRADE',
                    f'Bullish return (+${features.bar_5s_return:.2f}) is insufficient to overcome the BC.Game tie-loss house edge.',
                )
            if features.velocity_1s_bps < -0.15:
                return _make(
                    SignalDirection.NO_TRADE,
                    'NO_TRADE',
                    'Price velocity is decelerating or falling; entering UP risks immediate adverse movement.',
                )

        quality = 'STRONG' if (bull >= 8 and margin >= 4) or features.bar_5s_return >= 1.50 else 'VALID'
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
            if features.bar_5s_return > 0.40 or features.velocity_1s_bps > 0.15:
                return _make(
                    SignalDirection.NO_TRADE,
                    'NO_TRADE',
                    'Microstructure shows upward momentum; entering DOWN risks adverse upward breakout.',
                )

        quality = 'STRONG' if (bear >= 8 and margin >= 4) or features.bar_5s_return <= -1.50 else 'VALID'
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
