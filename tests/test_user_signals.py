import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import Signal, SignalDirection, SignalStatus
from app.services import user_signals
from app.services.user_signals import UserSignalService


@pytest.mark.asyncio
async def test_paper_mode_never_issues_actionable_user_signal(monkeypatch):
    monkeypatch.setattr(user_signals.settings, 'signal_mode', 'PAPER')
    result = await UserSignalService(None).request_scan(1, countdown_seconds=15)
    assert result.available is False
    assert result.signal is None
    assert 'PAPER' in result.reason


def test_database_prevents_two_current_signals_for_one_user():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        common = {
            'requested_by_user_id': 7,
            'market': 'BTC/USD',
            'product': 'BC_UPDOWN_5S',
            'direction': SignalDirection.UP,
            'strategy_version': 'BTC_UPDOWN_5S_V1.1',
        }
        db.add(Signal(status=SignalStatus.WAITING_ENTRY, **common))
        db.commit()
        db.add(Signal(status=SignalStatus.ACTIVE, **common))
        with pytest.raises(IntegrityError):
            db.commit()
