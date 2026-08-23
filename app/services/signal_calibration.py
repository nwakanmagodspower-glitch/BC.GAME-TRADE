from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, cast, literal, select
from sqlalchemy.orm import Session

from app.models.entities import AuditLog, Signal, SignalDirection

CALIBRATION_ACTION = 'signal_calibration_label'


@dataclass(frozen=True)
class CalibrationStats:
    labeled: int
    wins: int
    losses: int
    win_rate: float | None
    avg_win_edge: float | None
    avg_loss_edge: float | None


class SignalCalibrationService:
    """Owner-verified BCGAME outcomes for strategy research only.

    Labels are stored in AuditLog instead of mutating Signal.status, so the
    private research workflow cannot re-enable user WIN/LOSS notifications or
    interfere with lifecycle bookkeeping.
    """

    def __init__(self, db: Session):
        self.db = db

    def latest_unlabeled(self) -> Signal | None:
        labeled_targets = select(AuditLog.target).where(AuditLog.action == CALIBRATION_ACTION)
        target_expr = literal('signal:') + cast(Signal.id, String)
        return self.db.scalar(
            select(Signal)
            .where(
                Signal.direction.in_([SignalDirection.UP, SignalDirection.DOWN]),
                Signal.strategy_version == 'BTC_5S_UNIFIED_V2',
                target_expr.not_in(labeled_targets),
            )
            .order_by(Signal.id.desc())
        )

    def label(self, signal_id: int, outcome: str, actor_telegram_id: int) -> Signal:
        normalized = outcome.upper()
        if normalized not in {'WIN', 'LOSS'}:
            raise ValueError('Outcome must be WIN or LOSS.')
        signal = self.db.get(Signal, signal_id)
        if signal is None:
            raise ValueError('Signal not found.')
        if signal.direction not in {SignalDirection.UP, SignalDirection.DOWN}:
            raise ValueError('Only directional signals can be calibrated.')

        target = f'signal:{signal.id}'
        existing = self.db.scalar(
            select(AuditLog)
            .where(AuditLog.action == CALIBRATION_ACTION, AuditLog.target == target)
            .order_by(AuditLog.id.desc())
        )
        details = {
            'outcome': normalized,
            'direction': signal.direction.value,
            'strategy_version': signal.strategy_version,
            'confidence': signal.confidence,
        }
        if existing is None:
            self.db.add(AuditLog(
                actor_telegram_id=actor_telegram_id,
                action=CALIBRATION_ACTION,
                target=target,
                details=details,
            ))
        else:
            existing.actor_telegram_id = actor_telegram_id
            existing.details = details
        self.db.commit()
        return signal

    @staticmethod
    def signal_summary(signal: Signal) -> dict[str, Any]:
        data = signal.features_snapshot or {}
        engine = data.get('_engine') or {}
        horizon = data.get('_prediction_horizon') or {}
        cross = data.get('_cross_venue') or {}
        return {
            'id': signal.id,
            'direction': signal.direction.value,
            'created_at': signal.created_at,
            'edge': engine.get('edge'),
            'quality': engine.get('quality') or ((data.get('_decision') or {}).get('quality')),
            'seconds_until_start': horizon.get('seconds_until_start'),
            'contract_duration_seconds': horizon.get('contract_duration_seconds'),
            'volatility_5s': data.get('tick_volatility_5s_pct'),
            'return_1s': data.get('tick_return_1s_pct'),
            'return_3s': data.get('tick_return_3s_pct'),
            'return_5s': data.get('tick_return_5s_pct'),
            'trade_buy_ratio': data.get('trade_buy_ratio'),
            'cross_consensus': cross.get('consensus'),
        }

    def stats(self) -> CalibrationStats:
        rows = self.db.scalars(
            select(AuditLog)
            .where(AuditLog.action == CALIBRATION_ACTION)
            .order_by(AuditLog.id.asc())
        ).all()
        wins = 0
        losses = 0
        win_edges: list[float] = []
        loss_edges: list[float] = []
        for row in rows:
            details = row.details or {}
            outcome = str(details.get('outcome') or '').upper()
            target = row.target or ''
            try:
                signal_id = int(target.split(':', 1)[1])
            except (ValueError, IndexError):
                continue
            signal = self.db.get(Signal, signal_id)
            edge = None
            if signal is not None:
                engine = (signal.features_snapshot or {}).get('_engine') or {}
                raw_edge = engine.get('edge')
                if isinstance(raw_edge, (int, float)):
                    edge = abs(float(raw_edge))
            if outcome == 'WIN':
                wins += 1
                if edge is not None:
                    win_edges.append(edge)
            elif outcome == 'LOSS':
                losses += 1
                if edge is not None:
                    loss_edges.append(edge)
        labeled = wins + losses
        return CalibrationStats(
            labeled=labeled,
            wins=wins,
            losses=losses,
            win_rate=(wins / labeled) if labeled else None,
            avg_win_edge=(sum(win_edges) / len(win_edges)) if win_edges else None,
            avg_loss_edge=(sum(loss_edges) / len(loss_edges)) if loss_edges else None,
        )
