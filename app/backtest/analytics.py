from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.backtest.engine import BacktestReport, BacktestTrade


@dataclass(frozen=True)
class BucketStats:
    name: str
    signals: int
    wins: int
    losses: int
    ties: int
    win_rate_ex_ties: float | None


def _summarize(name: str, trades: list[BacktestTrade]) -> BucketStats:
    wins = sum(t.outcome == 'WIN' for t in trades)
    losses = sum(t.outcome == 'LOSS' for t in trades)
    ties = sum(t.outcome == 'TIE' for t in trades)
    resolved = wins + losses
    return BucketStats(
        name=name,
        signals=len(trades),
        wins=wins,
        losses=losses,
        ties=ties,
        win_rate_ex_ties=(wins / resolved * 100.0) if resolved else None,
    )


def breakdown_by_direction(report: BacktestReport) -> list[BucketStats]:
    buckets: dict[str, list[BacktestTrade]] = defaultdict(list)
    for trade in report.trades:
        buckets[trade.direction.value].append(trade)
    return [_summarize(name, trades) for name, trades in sorted(buckets.items())]


def breakdown_by_quality(report: BacktestReport) -> list[BucketStats]:
    buckets: dict[str, list[BacktestTrade]] = defaultdict(list)
    for trade in report.trades:
        buckets[trade.quality].append(trade)
    return [_summarize(name, trades) for name, trades in sorted(buckets.items())]


def breakdown_by_hour_utc(report: BacktestReport) -> list[BucketStats]:
    buckets: dict[int, list[BacktestTrade]] = defaultdict(list)
    for trade in report.trades:
        buckets[trade.entry_time.hour].append(trade)
    return [_summarize(f'{hour:02d}:00 UTC', buckets[hour]) for hour in sorted(buckets)]


def breakdown_by_structure(report: BacktestReport) -> list[BucketStats]:
    buckets: dict[str, list[BacktestTrade]] = defaultdict(list)
    for trade in report.trades:
        buckets[str(trade.features.get('structure', 'UNKNOWN'))].append(trade)
    return [_summarize(name, trades) for name, trades in sorted(buckets.items())]
