from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from itertools import product

from app.backtest.engine import BacktestReport, run_backtest
from app.integrations.market_data.base import Candle


@dataclass(frozen=True)
class ParameterSet:
    min_score: int
    min_margin: int


@dataclass(frozen=True)
class WalkForwardFold:
    fold: int
    train_start: object
    train_end: object
    validation_start: object
    validation_end: object
    selected: ParameterSet
    train_report: BacktestReport
    validation_report: BacktestReport


@dataclass(frozen=True)
class WalkForwardReport:
    folds: list[WalkForwardFold]
    validation_signals: int
    validation_wins: int
    validation_losses: int
    validation_ties: int
    validation_win_rate_ex_ties: float | None


def _score_candidate(report: BacktestReport) -> tuple[float, float, int]:
    """Prefer win rate, then coverage, while requiring enough observations."""
    rate = report.win_rate_ex_ties if report.win_rate_ex_ties is not None else -1.0
    return (rate, report.coverage_pct, report.signals)


def _slice(candles: list[Candle], start, end) -> list[Candle]:
    return [c for c in candles if c.open_time >= start and c.open_time < end]


def run_walk_forward(
    candles: list[Candle],
    *,
    train_days: int = 14,
    validation_days: int = 7,
    expiry_minutes: int = 5,
    min_scores: tuple[int, ...] = (5, 6, 7, 8),
    min_margins: tuple[int, ...] = (2, 3, 4),
    minimum_train_signals: int = 50,
) -> WalkForwardReport:
    closed = sorted((c for c in candles if c.closed), key=lambda c: c.open_time)
    if not closed:
        raise ValueError('candles required')
    if train_days < 1 or validation_days < 1:
        raise ValueError('train_days and validation_days must be positive')

    start = closed[0].open_time
    end = closed[-1].close_time
    cursor = start
    folds: list[WalkForwardFold] = []
    fold_number = 1

    while True:
        train_start = cursor
        train_end = train_start + timedelta(days=train_days)
        validation_start = train_end
        validation_end = validation_start + timedelta(days=validation_days)
        if validation_end > end:
            break

        train_candles = _slice(closed, train_start, train_end)
        validation_candles = _slice(closed, validation_start, validation_end)

        candidates: list[tuple[ParameterSet, BacktestReport]] = []
        for min_score, min_margin in product(min_scores, min_margins):
            try:
                report = run_backtest(
                    train_candles,
                    expiry_minutes=expiry_minutes,
                    min_score=min_score,
                    min_margin=min_margin,
                )
            except ValueError:
                continue
            if report.signals >= minimum_train_signals:
                candidates.append((ParameterSet(min_score, min_margin), report))

        if not candidates:
            cursor += timedelta(days=validation_days)
            continue

        selected, train_report = max(candidates, key=lambda item: _score_candidate(item[1]))
        validation_report = run_backtest(
            validation_candles,
            expiry_minutes=expiry_minutes,
            min_score=selected.min_score,
            min_margin=selected.min_margin,
        )
        folds.append(
            WalkForwardFold(
                fold=fold_number,
                train_start=train_start,
                train_end=train_end,
                validation_start=validation_start,
                validation_end=validation_end,
                selected=selected,
                train_report=train_report,
                validation_report=validation_report,
            )
        )
        fold_number += 1
        cursor += timedelta(days=validation_days)

    wins = sum(f.validation_report.wins for f in folds)
    losses = sum(f.validation_report.losses for f in folds)
    ties = sum(f.validation_report.ties for f in folds)
    signals = sum(f.validation_report.signals for f in folds)
    resolved = wins + losses
    rate = (wins / resolved * 100.0) if resolved else None

    return WalkForwardReport(
        folds=folds,
        validation_signals=signals,
        validation_wins=wins,
        validation_losses=losses,
        validation_ties=ties,
        validation_win_rate_ex_ties=rate,
    )
