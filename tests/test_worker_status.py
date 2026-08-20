import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import RuntimeSetting
from app.services.worker_heartbeat import WorkerHeartbeatService
from app.services.worker_status import get_worker_status


def test_structured_worker_heartbeat_reports_health():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc).isoformat()

    with Session() as db:
        db.add(RuntimeSetting(
            key=WorkerHeartbeatService.KEY,
            value=json.dumps({
                'timestamp': now,
                'healthy': True,
                'components': {
                    'coordinator_leader': True,
                    'signal_lifecycle_ok': True,
                    'market_stream_ok': True,
                },
            }, separators=(',', ':')),
        ))
        db.commit()
        status = get_worker_status(db)
        assert status.seen is True
        assert status.fresh is True
        assert status.healthy is True
        assert status.components['signal_lifecycle_ok'] is True


def test_legacy_timestamp_only_heartbeat_is_not_live_healthy():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        db.add(RuntimeSetting(key=WorkerHeartbeatService.KEY, value=datetime.now(timezone.utc).isoformat()))
        db.commit()
        status = get_worker_status(db)
        assert status.seen is True
        assert status.fresh is True
        assert status.healthy is False
