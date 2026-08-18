from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.backtest.engine import BacktestReport, run_backtest
from app.integrations.market_data.base import Candle
from app.signals.features import FeatureSnapshot


@dataclass(frozen=True)
class AblationResult:
    name: str
    report: BacktestReport
    win_rate_delta_pct: float | None
    coverage_delta_pct: float


def _baseline_rate(report: BacktestReport) -> float | None:
    return report.win_rate_ex_ties


def _neutralize(features: FeatureSnapshot, family: str) -> FeatureSnapshot:
    values = features.to_dict()

    if family == 'trend':
        midpoint = (features.ema_fast + features.ema_slow) / 2.0
        values['ema_fast'] = midpoint
        values['ema_slow'] = midpoint
    elif family == 'momentum':
        values['momentum_5_pct'] = 0.0
        values['rsi_14'] = 50.0
    elif family == 'structure':
        values['structure'] = 'RANGE'
    elif family == 'volume':
        values['volume_ratio'] = 1.0
        values['taker_buy_ratio'] = 0.5
    elif family == 'volatility':
        values['atr_14_pct'] = 0.10
    elif family == 'trade_flow':
        values['trade_buy_ratio'] = None
        values['trade_count_recent'] = 0
    else:
        raise ValueError(f'unknown feature family: {family}')

    return FeatureSnapshot(**values)


def run_ablation(
    candles: list[Candle],
    *,
    expiry_minutes: int = 5,
    min_score: int = 6,
    min_margin: int = 3,
    families: tuple[str, ...] = (
        'trend',
        'momentum',
        'structure',
        'volume',
        'volatility',
        'trade_flow',
    ),
) -> tuple[BacktestReport, list[AblationResult]]:
    """Measure whether removing one feature family helps or hurts.

    This is a research tool only. It does not change production strategy weights.
    The underlying backtest engine must support a feature transform callback.
    """
    baseline = run_backtest(
        candles,
        expiry_minutes=expiry_minutes,
        min_score=min_score,
        min_margin=min_margin,
    )

    results: list[AblationResult] = []
    base_rate = _baseline_rate(baseline)

    for family in families:
        def transform(snapshot: FeatureSnapshot, selected: str = family) -> FeatureSnapshot:
            return _neutralize(snapshot, selected)

        report = run_backtest(
            candles,
            expiry_minutes=expiry_minutes,
            min_score=min_score,
            min_margin=min_margin,
            feature_transform=transform,
        )
        rate = _baseline_rate(report)
        delta = None if base_rate is None or rate is None else rate - base_rate
        results.append(
            AblationResult(
                name=family,
                report=report,
                win_rate_delta_pct=delta,
                coverage_delta_pct=report.coverage_pct - baseline.coverage_pct,
            )
        )

    return baseline, results
