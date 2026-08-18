from __future__ import annotations

from dataclasses import dataclass

from app.backtest.qualification import QualificationResult, qualify_walk_forward
from app.backtest.walk_forward import WalkForwardReport


@dataclass(frozen=True)
class PromotionDecision:
    eligible: bool
    candidate_version: str
    reasons: tuple[str, ...]
    qualification: QualificationResult


def evaluate_promotion(
    report: WalkForwardReport,
    *,
    current_version: str,
    candidate_version: str,
) -> PromotionDecision:
    """Research-only gate for moving a changed strategy into PAPER testing.

    This does not deploy or activate anything. It only verifies that a candidate
    uses a new version label and passes the repository's walk-forward research
    qualification gate.
    """
    reasons: list[str] = []

    if not candidate_version or candidate_version == current_version:
        reasons.append('material strategy changes require a new strategy version')
    if not candidate_version.startswith('BTC_UPDOWN_'):
        reasons.append('candidate version must remain within BTC Up/Down scope')

    qualification = qualify_walk_forward(report)
    if not qualification.qualified_for_forward_test:
        reasons.extend(qualification.reasons)

    return PromotionDecision(
        eligible=not reasons,
        candidate_version=candidate_version,
        reasons=tuple(reasons),
        qualification=qualification,
    )
