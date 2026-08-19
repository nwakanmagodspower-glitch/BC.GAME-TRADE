from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Signal, SignalDirection, SignalStatus

settings = get_settings()


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
    avg_settlement_delay_seconds: float | None
    max_settlement_delay_seconds: float | None
    missing_entry_prices: int
    missing_expiry_prices: int
    stuck_active: int
    strategy_versions: tuple[str, ...]
    passable: bool
    blockers: tuple[str, ...]


class PaperValidationService:
    """Read-only M11 technical evidence from persisted paper signals."""

    def __init__(self, db: Session): self.db = db

    def build_report(self, *, limit: int = 1000) -> PaperValidationReport:
        signals = list(self.db.scalars(select(Signal).order_by(Signal.id.desc()).limit(limit)).all())
        directional = [s for s in signals if s.direction in {SignalDirection.UP, SignalDirection.DOWN}]
        settled = [s for s in directional if s.status in {SignalStatus.WIN, SignalStatus.LOSS, SignalStatus.TIE}]
        entry_delays: list[float] = []
        settlement_delays: list[float] = []
        now = datetime.now(timezone.utc)

        for signal in directional:
            meta = ((signal.features_snapshot or {}).get('_market') or {})
            activated_at_text = meta.get('activated_at')
            settled_at_text = meta.get('settled_at')
            if activated_at_text and signal.entry_at:
                try:
                    activated_at = datetime.fromisoformat(activated_at_text)
                    if activated_at.tzinfo is None: activated_at = activated_at.replace(tzinfo=timezone.utc)
                    entry_delays.append(abs((activated_at - signal.entry_at).total_seconds()))
                except ValueError: pass
            if settled_at_text and signal.expiry_at:
                try:
                    settled_at = datetime.fromisoformat(settled_at_text)
                    if settled_at.tzinfo is None: settled_at = settled_at.replace(tzinfo=timezone.utc)
                    settlement_delays.append(max(0.0, (settled_at - signal.expiry_at).total_seconds()))
                except ValueError: pass

        missing_entry = sum(s.status in {SignalStatus.ACTIVE, SignalStatus.WIN, SignalStatus.LOSS, SignalStatus.TIE} and s.reference_entry_price is None for s in directional)
        missing_expiry = sum(s.status in {SignalStatus.WIN, SignalStatus.LOSS, SignalStatus.TIE} and s.reference_expiry_price is None for s in directional)
        stuck_active = sum(s.status == SignalStatus.ACTIVE and s.expiry_at is not None and now > s.expiry_at and (now - s.expiry_at).total_seconds() > max(10, settings.market_data_max_age_seconds * 3) for s in directional)
        versions = tuple(sorted({s.strategy_version for s in signals}))

        blockers: list[str] = []
        if not signals: blockers.append('No paper scans have been recorded yet.')
        if directional and not settled: blockers.append('Directional signals exist but none have settled yet.')
        if missing_entry: blockers.append(f'{missing_entry} activated/settled signals are missing entry reference prices.')
        if missing_expiry: blockers.append(f'{missing_expiry} settled signals are missing expiry reference prices.')
        if stuck_active: blockers.append(f'{stuck_active} active signals remain unsettled well after expiry.')
        if entry_delays and max(entry_delays) > settings.signal_settlement_window_seconds:
            blockers.append('At least one external Start Rate reference exceeded the configured capture window.')
        if versions and any(v != settings.strategy_version for v in versions):
            blockers.append('Observed strategy-version drift in paper-validation records.')

        return PaperValidationReport(
            total_scans=len(signals), directional_signals=len(directional),
            no_trade=sum(s.status == SignalStatus.NO_TRADE for s in signals),
            waiting=sum(s.status == SignalStatus.WAITING_ENTRY for s in signals),
            active=sum(s.status == SignalStatus.ACTIVE for s in signals),
            cancelled=sum(s.status == SignalStatus.CANCELLED for s in signals),
            settled=len(settled), wins=sum(s.status == SignalStatus.WIN for s in settled),
            losses=sum(s.status == SignalStatus.LOSS for s in settled), ties=sum(s.status == SignalStatus.TIE for s in settled),
            avg_entry_delay_seconds=mean(entry_delays) if entry_delays else None,
            max_entry_delay_seconds=max(entry_delays) if entry_delays else None,
            avg_settlement_delay_seconds=mean(settlement_delays) if settlement_delays else None,
            max_settlement_delay_seconds=max(settlement_delays) if settlement_delays else None,
            missing_entry_prices=missing_entry, missing_expiry_prices=missing_expiry,
            stuck_active=stuck_active, strategy_versions=versions,
            passable=not blockers, blockers=tuple(blockers),
        )
