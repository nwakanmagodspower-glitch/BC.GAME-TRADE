from datetime import datetime, timedelta, timezone

from app.models.entities import Signal, SignalDirection, SignalStatus
from app.services.paper_validation import PaperValidationService


class ScalarResult:
    def __init__(self, items): self.items = items
    def all(self): return self.items


class DummyDB:
    def __init__(self, signals): self.signals = signals
    def scalars(self, statement): return ScalarResult(self.signals)


def signal(status, *, version='BTC_UPDOWN_5S_V1.1', entry_delay=0.5, settled=True):
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
