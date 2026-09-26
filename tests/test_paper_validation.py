from datetime import datetime, timedelta, timezone

from app.models.entities import Signal, SignalDirection, SignalStatus
from app.services.paper_validation import PaperValidationService


class ScalarResult:
    def __init__(self, items): self.items = items
    def all(self): return self.items


class DummyDB:
    def __init__(self, signals): self.signals = signals
    def scalars(self, statement): return ScalarResult(self.signals)


def signal(status, *, version='BTC_ORIGINAL_INTELLIGENCE_TIMER_V1', entry_delay=0.5, settled=True):
    now = datetime.now(timezone.utc)
    entry = now - timedelta(seconds=10)
    expiry = entry + timedelta(seconds=5)
    meta = {'activated_at': (entry + timedelta(seconds=entry_delay)).isoformat()}
    if settled:
        meta['settled_at'] = (expiry + timedelta(seconds=1)).isoformat()
    return Signal(
        market='BTC/USD', product='BC_UPDOWN_5S', direction=SignalDirection.UP, status=status,
        strategy_version=version, entry_at=entry, expiry_at=expiry,
        reference_entry_price=100.0 if status in {SignalStatus.ACTIVE, SignalStatus.WIN, SignalStatus.LOSS, SignalStatus.TIE} else None,
        reference_expiry_price=101.0 if status in {SignalStatus.WIN, SignalStatus.LOSS, SignalStatus.TIE} else None,
        features_snapshot={'_market': meta},
    )


def test_clean_settled_signal_is_passable():
    report = PaperValidationService(DummyDB([signal(SignalStatus.WIN)])).build_report()
    assert report.passable is True
    assert report.missing_entry_prices == 0
    assert report.missing_expiry_prices == 0


def test_entry_outside_window_blocks_validation():
    report = PaperValidationService(DummyDB([signal(SignalStatus.WIN, entry_delay=5.0)])).build_report()
    assert report.passable is False
    assert any('capture window' in blocker for blocker in report.blockers)


def test_strategy_version_drift_blocks_validation():
    report = PaperValidationService(DummyDB([signal(SignalStatus.WIN, version='BTC_UPDOWN_V2')])).build_report()
    assert report.passable is False
    assert any('strategy-version drift' in blocker for blocker in report.blockers)


def test_diagnostic_external_references_settle_passably():
    now = datetime.now(timezone.utc)
    entry = now - timedelta(seconds=10)
    expiry = entry + timedelta(seconds=5)
    meta = {
        'activated_at': (entry + timedelta(seconds=0.4)).isoformat(),
        'external_expiry_sampled_at': (expiry + timedelta(seconds=0.3)).isoformat(),
    }
    expired_signal = Signal(
        market='BTC/USD',
        product='BC_UPDOWN_5S',
        direction=SignalDirection.UP,
        status=SignalStatus.EXPIRED,
        strategy_version='BTC_ORIGINAL_INTELLIGENCE_TIMER_V1',
        entry_at=entry,
        expiry_at=expiry,
        reference_entry_price=100.0,
        reference_expiry_price=105.0,
        features_snapshot={'_market': meta},
    )
    report = PaperValidationService(DummyDB([expired_signal])).build_report()
    assert report.passable is True
    assert report.settled == 1
    assert report.wins == 1
    assert report.losses == 0
    assert report.avg_settlement_delay_seconds is not None
    assert report.blockers == ()
