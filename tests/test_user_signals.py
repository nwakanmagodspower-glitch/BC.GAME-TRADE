import pytest
from datetime import datetime, timedelta, timezone
import time
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.integrations.bcgame_rounds import (
    BCGameRoundDecision,
    BCGameRoundSnapshot,
)
from app.models.entities import Signal, SignalDirection, SignalStatus, User, UserStatus
from app.services import user_signals
from app.services.user_signals import UserSignalService


@pytest.mark.asyncio
async def test_paper_mode_never_issues_actionable_user_signal(monkeypatch):
    monkeypatch.setattr(user_signals.settings, 'signal_mode', 'PAPER')
    result = await UserSignalService(None).request_scan(1)
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
            'strategy_version': 'BTC_ORIGINAL_INTELLIGENCE_TIMER_V1',
        }
        db.add(Signal(status=SignalStatus.WAITING_ENTRY, **common))
        db.commit()
        db.add(Signal(status=SignalStatus.ACTIVE, **common))
        with pytest.raises(IntegrityError):
            db.commit()


def approved_session():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(telegram_user_id=99, status=UserStatus.APPROVED)
    db.add(user)
    db.commit()
    db.refresh(user)
    return db, user


@pytest.mark.asyncio
async def test_hybrid_uses_manual_fallback_only_when_feed_is_unavailable(monkeypatch):
    db, user = approved_session()
    monkeypatch.setattr(user_signals.settings, 'app_env', 'development')
    monkeypatch.setattr(user_signals.settings, 'signal_mode', 'LIVE')
    monkeypatch.setattr(user_signals.settings, 'signals_enabled', True)
    monkeypatch.setattr(user_signals.settings, 'signal_timing_mode', 'HYBRID_SYNC')

    async def unavailable():
        return BCGameRoundDecision(False, False, None, 'authorization unavailable')

    async def scan(_symbol, **_timing):
        return SimpleNamespace(service_available=True, reason='qualified')

    recorded = object()
    seen = {}

    def record(_self, _result, **kwargs):
        seen.update(kwargs)
        return recorded

    monkeypatch.setattr(user_signals.bcgame_round_service, 'current_round_decision', unavailable)
    monkeypatch.setattr(user_signals.signal_intelligence_service, 'scan', scan)
    monkeypatch.setattr(user_signals.SignalRecordService, 'record_scan', record)
    try:
        result = await UserSignalService(db).request_scan(user.id)
        assert result.available and result.signal is recorded
        assert seen['round_snapshot'] is None
        assert seen['trigger_mode'] == 'MANUAL_FALLBACK'
    finally:
        db.close()


@pytest.mark.asyncio
async def test_auto_sync_fails_closed_when_feed_is_unavailable(monkeypatch):
    db, user = approved_session()
    monkeypatch.setattr(user_signals.settings, 'app_env', 'development')
    monkeypatch.setattr(user_signals.settings, 'signal_mode', 'LIVE')
    monkeypatch.setattr(user_signals.settings, 'signals_enabled', True)
    monkeypatch.setattr(user_signals.settings, 'signal_timing_mode', 'AUTO_SYNC')

    async def unavailable():
        return BCGameRoundDecision(False, False, None, 'authorization unavailable')

    monkeypatch.setattr(user_signals.bcgame_round_service, 'current_round_decision', unavailable)
    try:
        result = await UserSignalService(db).request_scan(user.id)
        assert not result.available
        assert result.signal is None
        assert 'timing is refreshing' in result.reason
    finally:
        db.close()


@pytest.mark.asyncio
async def test_post_analysis_cutoff_suppresses_signal(monkeypatch):
    db, user = approved_session()
    monkeypatch.setattr(user_signals.settings, 'app_env', 'development')
    monkeypatch.setattr(user_signals.settings, 'signal_mode', 'LIVE')
    monkeypatch.setattr(user_signals.settings, 'signals_enabled', True)
    monkeypatch.setattr(user_signals.settings, 'signal_timing_mode', 'HYBRID_SYNC')
    monkeypatch.setattr(user_signals.settings, 'detrade_dispatch_min_remaining_ms', 8_000)
    now = datetime.now(timezone.utc)
    snapshot = BCGameRoundSnapshot(
        round_id='round-1', observed_at=now,
        order_closes_at=now + timedelta(seconds=8),
        start_rate_at=now + timedelta(seconds=8),
        end_rate_at=now + timedelta(seconds=13),
        stake_band='1-50', source='DETRADE_SYNC',
        deadline_monotonic=time.monotonic() + 7.5,
    )

    async def synchronized():
        return BCGameRoundDecision(True, True, snapshot, 'ok')

    async def scan(_symbol, **_timing):
        return SimpleNamespace(service_available=True, reason='qualified')

    monkeypatch.setattr(user_signals.bcgame_round_service, 'current_round_decision', synchronized)
    monkeypatch.setattr(user_signals.signal_intelligence_service, 'scan', scan)
    try:
        result = await UserSignalService(db).request_scan(user.id)
        assert not result.available
        assert result.signal is None
        assert 'too close to the cutoff' in result.reason
    finally:
        db.close()


@pytest.mark.asyncio
async def test_expired_signal_unblocks_user_for_new_scan(monkeypatch):
    db, user = approved_session()
    monkeypatch.setattr(user_signals.settings, 'app_env', 'development')
    monkeypatch.setattr(user_signals.settings, 'signal_mode', 'LIVE')
    monkeypatch.setattr(user_signals.settings, 'signals_enabled', True)
    monkeypatch.setattr(user_signals.settings, 'signal_timing_mode', 'MANUAL_SYNC')
    monkeypatch.setattr(user_signals.settings, 'signal_user_cooldown_seconds', 0.0)

    # Insert a WAITING_ENTRY signal whose expiry_at is in the past
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    expired_signal = Signal(
        requested_by_user_id=user.id,
        market='BTC/USD',
        product='BC_UPDOWN_5S',
        direction=SignalDirection.UP,
        status=SignalStatus.WAITING_ENTRY,
        strategy_version='BTC_ORIGINAL_INTELLIGENCE_TIMER_V1',
        expiry_at=past,
        created_at=past - timedelta(seconds=15),
    )
    db.add(expired_signal)
    db.commit()

    async def scan(_symbol, **_timing):
        return SimpleNamespace(service_available=True, reason='new scan ready')

    recorded = object()

    def record(_self, _result, **kwargs):
        return recorded

    monkeypatch.setattr(user_signals.signal_intelligence_service, 'scan', scan)
    monkeypatch.setattr(user_signals.SignalRecordService, 'record_scan', record)

    try:
        result = await UserSignalService(db).request_scan(user.id)
        assert result.available is True
        assert result.signal is recorded
        # The previous signal must be marked EXPIRED
        db.refresh(expired_signal)
        assert expired_signal.status == SignalStatus.EXPIRED
    finally:
        db.close()

