from __future__ import annotations

from dataclasses import dataclass

from app.models.entities import SignalDirection
from app.signals.scoring import ScoreResult


@dataclass(frozen=True)
class SignalDecision:
    direction: SignalDirection
    quality: str
    bull_score: int
    bear_score: int
    margin: int
    reason: str


def decide(score: ScoreResult, min_score: int = 6, min_margin: int = 3) -> SignalDecision:
    bull = score.bull_score
    bear = score.bear_score
    margin = abs(bull - bear)

    if bull >= min_score and bull - bear >= min_margin:
        quality = 'STRONG' if bull >= 8 and margin >= 4 else 'VALID'
        return SignalDecision(
            direction=SignalDirection.UP,
            quality=quality,
            bull_score=bull,
            bear_score=bear,
            margin=margin,
            reason='; '.join(score.reasons),
        )

    if bear >= min_score and bear - bull >= min_margin:
        quality = 'STRONG' if bear >= 8 and margin >= 4 else 'VALID'
        return SignalDecision(
            direction=SignalDirection.DOWN,
            quality=quality,
            bull_score=bull,
            bear_score=bear,
            margin=margin,
            reason='; '.join(score.reasons),
        )

    return SignalDecision(
        direction=SignalDirection.NO_TRADE,
        quality='NO_TRADE',
        bull_score=bull,
        bear_score=bear,
        margin=margin,
        reason='Evidence is not strong or one-sided enough for a trade.',
    )
