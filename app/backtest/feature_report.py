from __future__ import annotations

from dataclasses import dataclass

from app.backtest.ablation import AblationResult
from app.backtest.engine import BacktestReport


@dataclass(frozen=True)
class FeatureAssessment:
    family: str
    classification: str
    win_rate_delta_pct: float | None
    coverage_delta_pct: float
    signals: int
    reason: str


@dataclass(frozen=True)
class FeatureResearchReport:
    baseline_win_rate: float | None
    baseline_coverage_pct: float
    baseline_signals: int
    assessments: tuple[FeatureAssessment, ...]


def build_feature_research_report(
    baseline: BacktestReport,
    ablations: list[AblationResult],
    *,
    minimum_signals: int = 100,
    meaningful_delta_pct: float = 1.0,
) -> FeatureResearchReport:
    """Classify ablation evidence without changing production strategy logic.

    Interpretation is intentionally conservative:
    - HELPFUL: removing the family hurts win rate by at least the threshold.
    - HARMFUL_CANDIDATE: removing it improves win rate by at least the threshold.
    - INCONCLUSIVE: delta is small, missing, or sample size is insufficient.

    HARMFUL_CANDIDATE is research evidence only. It never authorizes removal.
    """
    assessments: list[FeatureAssessment] = []

    for item in ablations:
        delta = item.win_rate_delta_pct
        report = item.report

        if report.signals < minimum_signals:
            classification = 'INCONCLUSIVE'
            reason = (
                f'Only {report.signals} ablation signals; require at least '
                f'{minimum_signals} before interpreting the delta.'
            )
        elif delta is None:
            classification = 'INCONCLUSIVE'
            reason = 'Win-rate delta is unavailable because one side has no resolved outcomes.'
        elif delta <= -meaningful_delta_pct:
            classification = 'HELPFUL'
            reason = (
                f'Removing {item.name} reduced win rate by {abs(delta):.2f} percentage points.'
            )
        elif delta >= meaningful_delta_pct:
            classification = 'HARMFUL_CANDIDATE'
            reason = (
                f'Removing {item.name} improved win rate by {delta:.2f} percentage points; '
                'validate on unseen data before any strategy change.'
            )
        else:
            classification = 'INCONCLUSIVE'
            reason = (
                f'Win-rate delta of {delta:.2f} percentage points is below the '
                f'{meaningful_delta_pct:.2f}-point research threshold.'
            )

        assessments.append(
            FeatureAssessment(
                family=item.name,
                classification=classification,
                win_rate_delta_pct=delta,
                coverage_delta_pct=item.coverage_delta_pct,
                signals=report.signals,
                reason=reason,
            )
        )

    return FeatureResearchReport(
        baseline_win_rate=baseline.win_rate_ex_ties,
        baseline_coverage_pct=baseline.coverage_pct,
        baseline_signals=baseline.signals,
        assessments=tuple(assessments),
    )
