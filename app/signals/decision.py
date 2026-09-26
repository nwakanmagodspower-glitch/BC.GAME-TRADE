from __future__ import annotations

from dataclasses import dataclass

from app.models.entities import SignalDirection
from app.signals.contracts import PredictionTarget, ScanStage
from app.signals.features import FeatureSnapshot
from app.signals.scoring import ScoreResult


@dataclass(frozen=True)
class SignalDecision:
    direction: SignalDirection
    quality: str
    bull_score: int
    bear_score: int
    margin: int
    reason: str


def decide(
    score: ScoreResult,
    min_score: int = 5,
    min_margin: int = 2,
    *,
    target: PredictionTarget | None = None,
    features: FeatureSnapshot | None = None,
    min_lead_range: float = 0.0,
) -> SignalDecision:
    bull = score.bull_score
    bear = score.bear_score
    margin = abs(bull - bear)

    if target is not None and target.scan_stage == ScanStage.POST_CUTOFF:
        return SignalDecision(
            direction=SignalDirection.NO_TRADE,
            quality='POST_CUTOFF',
            bull_score=bull,
            bear_score=bear,
            margin=margin,
            reason=f'Authoritative trade cutoff for round {target.round_id} has elapsed.',
        )

    target_prefix = f'Target [{target.round_id} {target.lead_time_seconds:.1f}s lead]: ' if target else ''

    # Speed & Volatility Gate:
    # If recent trade range before contract start is below the minimum threshold,
    # the market is in flat micro-chop where 5-second outcomes are noise and flat ties lose.
    if features is not None and min_lead_range > 0.0 and features.lead_range_dollars < min_lead_range:
        return SignalDecision(
            direction=SignalDirection.NO_TRADE,
            quality='LOW_SPEED',
            bull_score=bull,
            bear_score=bear,
            margin=margin,
            reason=(
                f'{target_prefix}Market speed is low (BTC range ${features.lead_range_dollars:.2f} < ${min_lead_range:.2f}). '
                'Preserving balance from flat chop losses.'
            ),
        )

    if bull >= min_score and bull - bear >= min_margin:
        if target is not None and target.scan_stage == ScanStage.STAGE_A_PREPARING:
            quality = 'PREPARING'
        else:
            quality = 'STRONG' if bull >= 5 and margin >= 2 else 'VALID'
        return SignalDecision(
            direction=SignalDirection.UP,
            quality=quality,
            bull_score=bull,
            bear_score=bear,
            margin=margin,
            reason=target_prefix + '; '.join(score.reasons),
        )

    if bear >= min_score and bear - bull >= min_margin:
        if target is not None and target.scan_stage == ScanStage.STAGE_A_PREPARING:
            quality = 'PREPARING'
        else:
            quality = 'STRONG' if bear >= 5 and margin >= 2 else 'VALID'
        return SignalDecision(
            direction=SignalDirection.DOWN,
            quality=quality,
            bull_score=bull,
            bear_score=bear,
            margin=margin,
            reason=target_prefix + '; '.join(score.reasons),
        )

    return SignalDecision(
        direction=SignalDirection.NO_TRADE,
        quality='NO_TRADE',
        bull_score=bull,
        bear_score=bear,
        margin=margin,
        reason=(target_prefix + '; '.join(score.reasons)) if score.reasons else 'Evidence is not strong or one-sided enough for a trade.',
    )
