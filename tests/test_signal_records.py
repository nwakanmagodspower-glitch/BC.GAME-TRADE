from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.integrations.bcgame_rounds import BCGameRoundSnapshot
from app.models.entities import BCGameRound, SignalDirection
from app.services.signal_records import SignalRecordService


def intelligence(direction):
    return SimpleNamespace(
        service_available=True,
        market='BTCUSDT',
        direction=direction,
        features=None,
        decision=None,
        quality='QUALIFIED',
        reference_price=70_000.0,
        market_snapshot=None,
        reason='test',
    )


def synchronized_round():
    now = datetime.now(timezone.utc)
    return BCGameRoundSnapshot(
        round_id='shared-round',
        observed_at=now,
        order_closes_at=now + timedelta(seconds=12),
        start_rate_at=now + timedelta(seconds=12),
        end_rate_at=now + timedelta(seconds=17),
        stake_band='1-50',
        source='DETRADE_SYNC',
    )


def test_directional_signals_reuse_one_synchronized_round_row():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        service = SignalRecordService(db)
        snapshot = synchronized_round()
        service.record_scan(intelligence(SignalDirection.UP), round_snapshot=snapshot)
        service.record_scan(intelligence(SignalDirection.DOWN), round_snapshot=snapshot)
        assert db.scalar(select(func.count(BCGameRound.id))) == 1


def test_no_trade_scan_does_not_create_round_row():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        SignalRecordService(db).record_scan(
            intelligence(SignalDirection.NO_TRADE),
            round_snapshot=synchronized_round(),
        )
        assert db.scalar(select(func.count(BCGameRound.id))) == 0
