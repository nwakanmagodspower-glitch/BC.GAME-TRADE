from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, pstdev

from app.backtest.walk_forward import WalkForwardReport


@dataclass(frozen=True)
class QualificationResult:
    qualified_for_forward_test: bool
    reasons: list[str]
    validation_signals: int
    validation_win_rate: float | None
    wilson_lower_bound_pct: float | None
    fold_win_rate_stddev: float | None
    positive_folds: int
    total_folds: int


def _wilson_lower_bound(wins: int, losses: int, z: float = 1.96) -> float | None:
    n = wins + losses
    if n == 0:
        return None
    p = wins / n
    denominator = 1 + (z * z / n)
    centre = p + (z * z / (2 * n))
    margin = z * sqrt((p * (1 - p) / n) + (z * z / (4 * n * n)))
    return ((centre - margin) / denominator) * 100.0


def qualify_walk_forward(
    report: WalkForwardReport,
    *,
    minimum_folds: int = 3,
    minimum_validation_signals: int = 150,
    minimum_win_rate_pct: float = 55.0,
    minimum_positive_fold_fraction: float = 0.60,
    maximum_fold_stddev_pct: float = 12.0,
) -> QualificationResult:
    """Gate a strategy for PAPER forward testing only, never for profitability claims.

    This intentionally does not include payout/EV because BC.GAME payout behavior is not
    yet verified. Passing means 'worth forward-testing', not 'profitable' or 'production ready'.
    """
    reasons: list[str] = []
    fold_rates = [
        fold.validation_report.win_rate_ex_ties
        for fold in report.folds
        if fold.validation_report.win_rate_ex_ties is not None
    ]
    positive_folds = sum(rate >= minimum_win_rate_pct for rate in fold_rates)
    total_folds = len(report.folds)
    stddev = pstdev(fold_rates) if len(fold_rates) >= 2 else None
    lower = _wilson_lower_bound(report.validation_wins, report.validation_losses)

    if total_folds < minimum_folds:
        reasons.append(f'Only {total_folds} validation folds; require at least {minimum_folds}.')
    if report.validation_signals < minimum_validation_signals:
        reasons.append(
            f'Only {report.validation_signals} validation signals; require at least {minimum_validation_signals}.'
        )
    rate = report.validation_win_rate_ex_ties
    if rate is None or rate < minimum_win_rate_pct:
        reasons.append(f'Validation win rate {rate} is below the {minimum_win_rate_pct:.2f}% research threshold.')
    required_positive = max(1, int(total_folds * minimum_positive_fold_fraction + 0.999999)) if total_folds else 1
    if positive_folds < required_positive:
        reasons.append(
            f'Only {positive_folds}/{total_folds} folds meet the research win-rate threshold; require {required_positive}.'
        )
    if stddev is not None and stddev > maximum_fold_stddev_pct:
        reasons.append(
            f'Fold win-rate dispersion is {stddev:.2f}%, above the {maximum_fold_stddev_pct:.2f}% stability limit.'
        )

    return QualificationResult(
        qualified_for_forward_test=not reasons,
        reasons=reasons or ['Walk-forward evidence is sufficient to proceed to PAPER forward testing.'],
        validation_signals=report.validation_signals,
        validation_win_rate=rate,
        wilson_lower_bound_pct=lower,
        fold_win_rate_stddev=stddev,
        positive_folds=positive_folds,
        total_folds=total_folds,
    )
