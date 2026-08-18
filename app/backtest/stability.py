from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import mean

from app.backtest.ablation import run_ablation
from app.backtest.reporting import FeatureAssessment, assess_ablation
from app.integrations.market_data.base import Candle


@dataclass(frozen=True)
class StabilityWindow:
    start: datetime
    end: datetime
    assessments: tuple[FeatureAssessment, ...]


@dataclass(frozen=True)
class FeatureStability:
    family: str
    windows: int
    helpful_windows: int
    harmful_candidate_windows: int
    inconclusive_windows: int
    mean_win_rate_delta_pct: float | None
    stable_classification: str


@dataclass(frozen=True)
class StabilityReport:
    windows: tuple[StabilityWindow, ...]
    features: tuple[FeatureStability, ...]


def run_feature_stability(
    candle_windows: list[list[Candle]],
    *,
    expiry_minutes: int = 5,
    min_score: int = 6,
    min_margin: int = 3,
    minimum_signals: int = 100,
    meaningful_delta_pct: float = 1.0,
) -> StabilityReport:
    """Repeat feature ablation over separate chronological windows.

    This is research-only. A stable classification is evidence, not permission
    to change production strategy weights or feature families.
    """
    window_results: list[StabilityWindow] = []
    by_family: dict[str, list[FeatureAssessment]] = {}

    for candles in candle_windows:
        if not candles:
            continue
        baseline, ablations = run_ablation(
            candles,
            expiry_minutes=expiry_minutes,
            min_score=min_score,
            min_margin=min_margin,
        )
        assessments = assess_ablation(
            baseline,
            ablations,
            minimum_signals=minimum_signals,
            meaningful_delta_pct=meaningful_delta_pct,
        )
        window_results.append(
            StabilityWindow(
                start=candles[0].open_time,
                end=candles[-1].close_time,
                assessments=tuple(assessments),
            )
        )
        for item in assessments:
            by_family.setdefault(item.family, []).append(item)

    feature_results: list[FeatureStability] = []
    for family, items in sorted(by_family.items()):
        helpful = sum(item.classification == 'HELPFUL' for item in items)
        harmful = sum(item.classification == 'HARMFUL_CANDIDATE' for item in items)
        inconclusive = sum(item.classification == 'INCONCLUSIVE' for item in items)
        deltas = [item.win_rate_delta_pct for item in items if item.win_rate_delta_pct is not None]

        # Require consistency across at least three independent windows. Mixed
        # evidence remains inconclusive instead of being averaged into a claim.
        if len(items) >= 3 and helpful / len(items) >= 0.67 and harmful == 0:
            classification = 'STABLY_HELPFUL'
        elif len(items) >= 3 and harmful / len(items) >= 0.67 and helpful == 0:
            classification = 'STABLY_HARMFUL_CANDIDATE'
        else:
            classification = 'INCONCLUSIVE'

        feature_results.append(
            FeatureStability(
                family=family,
                windows=len(items),
                helpful_windows=helpful,
                harmful_candidate_windows=harmful,
                inconclusive_windows=inconclusive,
                mean_win_rate_delta_pct=mean(deltas) if deltas else None,
                stable_classification=classification,
            )
        )

    return StabilityReport(tuple(window_results), tuple(feature_results))
