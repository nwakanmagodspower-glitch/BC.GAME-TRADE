from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Signal, SignalDirection, SignalStatus


@dataclass(frozen=True)
class PaperValidationReport:
    total_scans: int
    directional_signals: int
    no_trade: int
    waiting: int
    active: int
    cancelled: int
    settled: int
    wins: int
    losses: int
    ties: int
    avg_entry_delay_seconds: float | None
    max_entry_delay_seconds: float | None
    missing_entry_prices: int
    missing_expiry_prices: int
    strategy_versions: tuple[str, ...]
    passable: bool
    blockers: tuple[str, ...]


class PaperValidationService:
    """Read-only M11 runtime evidence from persisted paper signals."""

    def __init__(self, db: Session):
        self.db = db

    def build_report(self, *, limit: int = 1000) -> PaperValidationReport:
        signals = list(self.db.scalars(select(Signal).order_by(Signal.id.desc()).limit(limit)).all())
        directional = [s for s in signals if s.direction in {SignalDirection.UP, SignalDirection.DOWN}]
        settled = [s for s in directional if s.status in {SignalStatus.WIN, SignalStatus.LOSS, SignalStatus.TIE}]

        delays: list[float] = []
        for signal in directional:
            market_meta = ((signal.features_snapshot or {}).get('_market') or {})
            activated_at_text = market_meta.get('activated_at')
            if activated_at_text and signal.entry_at:
                try:
                    activated_at = datetime.fromisoformat(activated_at_text)
                    if activated_at.tzinfo is None:
                        activated_at = activated_at.replace(tzinfo=timezone.utc)
                    delays.append(abs((activated_at - signal.entry_at).total_seconds()))
                except ValueError:
                    pass

        blockers: list[str] = []
        if not signals:
            blockers.append('No paper scans have been recorded yet.')
        if directional and not settled:
            blockers.append('Directional signals exist but none have settled yet.')
        missing_entry = sum(s.status in {SignalStatus.ACTIVE, SignalStatus.WIN, SignalStatus.LOSS, SignalStatus.TIE} and s.reference_entry_price is None for s in directional)
        missing_expiry = sum(s.status in {SignalStatus.WIN, SignalStatus.LOSS, SignalStatus.TIE} and s.reference_expiry_price is None for s in directional)
        if missing_entry:
            blockers.append(f'{missing_entry} activated/settled signals are missing entry reference prices.')
        if missing_expiry:
            blockers.append(f'{missing_expiry} settled signals are missing expiry reference prices.')

        return PaperValidationReport(
            total_scans=len(signals),
            directional_signals=len(directional),
            no_trade=sum(s.status == SignalStatus.NO_TRADE for s in signals),
            waiting=sum(s.status == SignalStatus.WAITING_ENTRY for s in signals),
            active=sum(s.status == SignalStatus.ACTIVE for s in signals),
            cancelled=sum(s.status == SignalStatus.CANCELLED for s in signals),
            settled=len(settled),
            wins=sum(s.status == SignalStatus.WIN for s in settled),
            losses=sum(s.status == SignalStatus.LOSS for s in settled),
            ties=sum(s.status == SignalStatus.TIE for s in settled),
            avg_entry_delay_seconds=mean(delays) if delays else None,
            max_entry_delay_seconds=max(delays) if delays else None,
            missing_entry_prices=missing_entry,
            missing_expiry_prices=missing_expiry,
            strategy_versions=tuple(sorted({s.strategy_version for s in signals})),
            passable=not blockers,
            blockers=tuple(blockers),
        )
