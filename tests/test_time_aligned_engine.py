import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.integrations.bcgame_rounds import BCGameRoundDecision, BCGameRoundSnapshot
from app.integrations.market_data.base import Candle, MarketTick
from app.models.entities import SignalDirection, User, UserStatus
from app.services.market_data import MarketSnapshot
from app.services.signal_intelligence import SignalIntelligenceService
from app.services.user_signals import UserSignalService
from app.signals.contracts import PredictionTarget, RoundPredictionContext, ScanStage
from app.signals.decision import decide
from app.signals.features import build_features
from app.signals.scoring import score_features


def make_test_candles(direction: int = 1, rsi_extreme: bool = False) -> list[Candle]:
    now = datetime.now(timezone.utc) - timedelta(minutes=60)
    candles = []
    price = 60000.0
    for i in range(60):
        open_price = price
        if rsi_extreme and i >= 45:
            step = 100.0 * direction
            taker_ratio = 0.90 if direction > 0 else 0.10
        elif direction != 0:
            if i in (48, 49, 50, 51):
                step = -15.0 * direction
                taker_ratio = 0.45 if direction > 0 else 0.55
            else:
                step = 14.0 * direction
                taker_ratio = 0.65 if direction > 0 else 0.35
        else:
            step = 2.0 if i % 2 else -2.0
            taker_ratio = 0.50
        close_price = price + step
        high = max(open_price, close_price) + 8
        low = min(open_price, close_price) - 8
        vol = 100 + i
        candles.append(Candle(
            symbol='BTCUSDT', interval='1m', open_time=now + timedelta(minutes=i),
            close_time=now + timedelta(minutes=i + 1), open=open_price, high=high, low=low,
            close=close_price, volume=vol, quote_volume=0, trade_count=100,
            taker_buy_base_volume=vol * taker_ratio,
            taker_buy_quote_volume=0, closed=True, provider='TEST',
        ))
        price = close_price
    return candles


def make_test_ticks(bullish: bool = True, count: int = 24) -> list[MarketTick]:
    now = datetime.now(timezone.utc)
    ticks = []
    for i in range(count):
        ticks.append(MarketTick(
            symbol='BTCUSDT', price=61000.0, quantity=1.0,
            event_time=now - timedelta(milliseconds=(count - 1 - i) * 250),
            provider='TEST', is_buyer_maker=not bullish,
        ))
    return ticks


def make_round_context(
    round_id: str = 'ROUND-100',
    seconds_until_start: float = 8.0,
    duration_seconds: float = 5.0,
    status: int = 1001,
    phase: str = 'BETTING',
    is_fresh: bool = True,
) -> RoundPredictionContext:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms + int(seconds_until_start * 1000)
    end_ms = start_ms + int(duration_seconds * 1000)
    return RoundPredictionContext(
        round_id=round_id,
        current_server_time_ms=now_ms,
        price_start_time_ms=start_ms,
        price_end_time_ms=end_ms,
        trade_cutoff_time_ms=start_ms - 100,
        seconds_until_start=seconds_until_start,
        contract_duration_seconds=duration_seconds,
        status=status,
        phase=phase,
        is_fresh=is_fresh,
        observed_at=datetime.now(timezone.utc),
        feed_age_ms=100 if is_fresh else 5000,
    )


# 1. Verification of Progression: 15s, 8s, 4s, and 2s before T1 all remain targeted to [T1, T2]
@pytest.mark.asyncio
async def test_exact_lead_time_progression_15s_8s_4s_2s_remain_targeted_to_t1_t2():
    candles = make_test_candles(1)
    ticks = make_test_ticks(True)

    # Fixed BC.Game contract start T1 and end T2
    now = datetime.now(timezone.utc)
    t1 = now + timedelta(seconds=20)
    t2 = t1 + timedelta(seconds=5)
    round_id = 'ROUND-TARGET-ALIGN'

    # Test progression at 15s, 8s, 4s, and 2s before T1
    for lead_seconds, expected_stage, expected_quality in [
        (15.0, ScanStage.STAGE_A_PREPARING, 'PREPARING'),
        (8.0, ScanStage.STAGE_B_FINAL, 'VALID'),
        (4.0, ScanStage.STAGE_B_FINAL, 'VALID'),
        (2.0, ScanStage.STAGE_B_FINAL, 'VALID'),
    ]:
        scan_time = t1 - timedelta(seconds=lead_seconds)
        target = PredictionTarget(
            round_id=round_id,
            target_start=t1,
            target_end=t2,
            lead_time_seconds=lead_seconds,
            duration_seconds=5.0,
            scan_time=scan_time,
            trade_cutoff=t1 - timedelta(milliseconds=100),
            seconds_until_cutoff=lead_seconds - 0.1,
        )

        # 1. Target interval MUST strictly be [T1, T2] at every lead interval
        assert target.target_start == t1
        assert target.target_end == t2
        assert target.duration_seconds == 5.0
        assert target.lead_time_seconds == lead_seconds
        assert target.scan_stage == expected_stage
        assert target.is_authoritative_post_cutoff is False

        # 2. Features and scoring maintain explicit temporal target
        features = build_features(candles, ticks, target=target)
        assert features.target_round_id == round_id
        assert features.target_lead_time_seconds == lead_seconds
        assert features.target_duration_seconds == 5.0

        score = score_features(features)
        decision = decide(score, min_score=3, min_margin=1, target=target)

        # 3. Decision direction is UP and targets [T1, T2]
        assert decision.direction == SignalDirection.UP
        if expected_quality == 'PREPARING':
            assert decision.quality == 'PREPARING'
        else:
            assert decision.quality in {'VALID', 'STRONG'}

        assert f'Target [{round_id} {lead_seconds:.1f}s lead]' in decision.reason

        # 4. Separation of prediction from execution authorization:
        # At 15s, 4s, and 2s, delivery dispatch with an 8.0s safety margin is NOT authorized,
        # but at 8.0s lead (with cutoff 7.9s), dispatch margin can be verified independently
        if lead_seconds < 8.0:
            assert target.execution_authorized(min_dispatch_margin_seconds=8.0) is False
        assert target.execution_authorized(min_dispatch_margin_seconds=1.0) is True


# 2. Authoritative cutoff derived from observer's tradeCutoffTime, not an arbitrary 2s constant
@pytest.mark.asyncio
async def test_authoritative_trade_cutoff_rejection():
    # 2 seconds before T1 is NOT post-cutoff if tradeCutoffTime has not elapsed
    target_active_at_2s = PredictionTarget(
        round_id='ROUND-CUTOFF-TEST',
        target_start=datetime.now(timezone.utc) + timedelta(seconds=2),
        target_end=datetime.now(timezone.utc) + timedelta(seconds=7),
        lead_time_seconds=2.0,
        duration_seconds=5.0,
        scan_time=datetime.now(timezone.utc),
        trade_cutoff=datetime.now(timezone.utc) + timedelta(seconds=1.9),
        seconds_until_cutoff=1.9,
    )
    assert target_active_at_2s.is_authoritative_post_cutoff is False
    assert target_active_at_2s.scan_stage == ScanStage.STAGE_B_FINAL

    # Now simulate when server time has genuinely reached or exceeded tradeCutoffTime
    target_post_cutoff = PredictionTarget(
        round_id='ROUND-CUTOFF-TEST',
        target_start=datetime.now(timezone.utc),
        target_end=datetime.now(timezone.utc) + timedelta(seconds=5),
        lead_time_seconds=0.0,
        duration_seconds=5.0,
        scan_time=datetime.now(timezone.utc),
        trade_cutoff=datetime.now(timezone.utc) - timedelta(milliseconds=100),
        seconds_until_cutoff=-0.1,
    )
    assert target_post_cutoff.is_authoritative_post_cutoff is True
    assert target_post_cutoff.scan_stage == ScanStage.POST_CUTOFF

    score = score_features(build_features(make_test_candles(1), make_test_ticks(True), target=target_post_cutoff))
    decision = decide(score, min_score=3, min_margin=1, target=target_post_cutoff)
    assert decision.direction == SignalDirection.NO_TRADE
    assert decision.quality == 'POST_CUTOFF'
    assert 'Authoritative trade cutoff' in decision.reason


# 5. Round lifecycle phases: BETTING, TRADE_CUTOFF, PAY_OUT, FINISHED, CANCELLED
@pytest.mark.asyncio
async def test_round_lifecycle_phases():
    service = SignalIntelligenceService()

    # BETTING (1001) is tradeable
    betting_ctx = make_round_context(status=1001, phase='BETTING')
    assert betting_ctx.can_predict is True

    # Non-betting phases must fail closed with NO_TRADE
    for status, phase in [
        (1002, 'START_PAY_OUT'),
        (1003, 'TRADE_CUTOFF'),
        (1004, 'PAY_OUT'),
        (1005, 'FINISHED'),
        (1006, 'READY_TO_START'),
        (1007, 'CANCELLED'),
        (1008, 'NON_TRADEABLE_TRANSITION'),
    ]:
        ctx = make_round_context(status=status, phase=phase)
        assert ctx.can_predict is False
        res = await service.scan('BTCUSDT', round_context=ctx)
        assert res.direction == SignalDirection.NO_TRADE
        assert f'not open for betting ({phase})' in res.reason


# 6. Round Identity: New round ID creates fresh context and never reuses old cache
@pytest.mark.asyncio
async def test_new_round_id_never_reuses_old_cache(monkeypatch):
    service = SignalIntelligenceService()
    now = datetime.now(timezone.utc)

    mock_snapshot = MarketSnapshot(
        symbol='BTCUSDT', price=60500.0, event_time=now,
        provider='TEST', age_seconds=0.1, fresh=True, last_quantity=1.0, is_buyer_maker=False,
    )

    async def fake_get_snapshot(*args, **kwargs):
        return mock_snapshot

    async def fake_get_candles(*args, **kwargs):
        return make_test_candles(1)

    async def fake_get_ticks(*args, **kwargs):
        return make_test_ticks(True)

    monkeypatch.setattr('app.services.market_data.market_data_service.cache.get_snapshot', fake_get_snapshot)
    monkeypatch.setattr('app.services.market_data.market_data_service.get_cached_candles', fake_get_candles)
    monkeypatch.setattr('app.services.market_data.market_data_service.cache.get_recent_ticks', fake_get_ticks)

    ctx1 = make_round_context(round_id='ROUND-AAA', seconds_until_start=8.0)
    res1 = await service.scan('BTCUSDT', round_context=ctx1)
    assert res1.target is not None
    assert res1.target.round_id == 'ROUND-AAA'
    assert res1.direction == SignalDirection.UP

    # Immediately request for a new round ID ROUND-BBB within the 300ms cache window
    ctx2 = make_round_context(round_id='ROUND-BBB', seconds_until_start=7.9)
    res2 = await service.scan('BTCUSDT', round_context=ctx2)
    assert res2.target is not None
    assert res2.target.round_id == 'ROUND-BBB'
    assert res2.target.round_id != res1.target.round_id


# 7. Stale observation fails closed
@pytest.mark.asyncio
async def test_stale_observation_fails_closed():
    service = SignalIntelligenceService()
    ctx = make_round_context(is_fresh=False)
    res = await service.scan('BTCUSDT', round_context=ctx)
    assert res.direction == SignalDirection.NO_TRADE
    assert res.quality == 'STALE_OBSERVATION'
    assert 'stale' in res.reason


# 8. Stale market data fails closed
@pytest.mark.asyncio
async def test_stale_market_data_fails_closed(monkeypatch):
    service = SignalIntelligenceService()
    stale_snapshot = MarketSnapshot(
        symbol='BTCUSDT', price=60500.0,
        event_time=datetime.now(timezone.utc) - timedelta(seconds=10),
        provider='TEST', age_seconds=10.0, fresh=False, last_quantity=1.0, is_buyer_maker=False,
    )

    async def fake_get_snapshot(*args, **kwargs):
        return stale_snapshot

    monkeypatch.setattr('app.services.market_data.market_data_service.cache.get_snapshot', fake_get_snapshot)

    ctx = make_round_context(seconds_until_start=8.0)
    res = await service.scan('BTCUSDT', round_context=ctx)
    assert res.direction == SignalDirection.NO_TRADE
    assert 'stale' in res.reason


# 9. Round ID mismatch between prediction and active round fails closed
@pytest.mark.asyncio
async def test_round_id_mismatch_fails_closed(monkeypatch):
    monkeypatch.setattr('app.services.user_signals.settings.signal_mode', 'LIVE')
    monkeypatch.setattr('app.services.user_signals.settings.signals_enabled', True)
    monkeypatch.setattr('app.services.user_signals.settings.signal_timing_mode', 'AUTO_SYNC')
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(telegram_user_id=101, status=UserStatus.APPROVED)
    db.add(user)
    db.commit()

    now = datetime.now(timezone.utc)
    snapshot = BCGameRoundSnapshot(
        round_id='ACTIVE-ROUND-1', observed_at=now,
        order_closes_at=now + timedelta(seconds=12),
        start_rate_at=now + timedelta(seconds=12),
        end_rate_at=now + timedelta(seconds=17),
        stake_band='1-50', source='DETRADE_SYNC',
    )

    # Return prediction for a mismatched round ID (e.g. from an old cycle)
    mismatched_target = PredictionTarget(
        round_id='OLD-ROUND-0',
        target_start=now + timedelta(seconds=10),
        target_end=now + timedelta(seconds=15),
        lead_time_seconds=10.0,
        duration_seconds=5.0,
        scan_time=now,
    )

    async def fake_decision():
        return BCGameRoundDecision(True, True, snapshot, 'ok')

    async def fake_scan(_symbol, **_timing):
        return SimpleNamespace(
            market='BTCUSDT',
            service_available=True,
            direction=SignalDirection.UP,
            quality='VALID',
            reason='bullish',
            target=mismatched_target,
        )

    monkeypatch.setattr('app.services.user_signals.bcgame_round_service.current_round_decision', fake_decision)
    monkeypatch.setattr('app.services.user_signals.signal_intelligence_service.scan', fake_scan)

    result = await UserSignalService(db).request_scan(user.id)
    assert result.available is False
    assert result.signal is None
    assert 'Round changed while scanning' in result.reason
    db.close()


# 10. Contract duration != 5 seconds rejected
@pytest.mark.asyncio
async def test_invalid_contract_duration_rejected():
    service = SignalIntelligenceService()
    # BC.Game 8-second or 3-second contract is not the configured 5s contract
    ctx = make_round_context(duration_seconds=8.0)
    res = await service.scan('BTCUSDT', round_context=ctx)
    assert res.direction == SignalDirection.NO_TRADE
    assert res.quality == 'INVALID_CONTRACT'
    assert '5-second' in res.reason


# 11. Prediction valid for NOW but invalid for future contract window (Impulse Exhaustion)
@pytest.mark.asyncio
async def test_premature_impulse_exhaustion_before_contract_window():
    # Simulate an overbought spike at T0 (RSI ~79)
    candles = make_test_candles(1, rsi_extreme=True)
    ticks = make_test_ticks(True)

    # With lead_time_seconds = 8.0s, the impulse at T0 is recognized as prone to exhaustion before T1
    target = PredictionTarget(
        round_id='ROUND-EXHAUST',
        target_start=datetime.now(timezone.utc) + timedelta(seconds=8),
        target_end=datetime.now(timezone.utc) + timedelta(seconds=13),
        lead_time_seconds=8.0,
        duration_seconds=5.0,
        scan_time=datetime.now(timezone.utc),
    )

    features = build_features(candles, ticks, target=target)
    assert features.impulse_exhaustion_risk is True

    score = score_features(features)
    # The score penalty for exhaustion before T1 prevents a premature UP trade
    assert any('exhaustion across 8.0s lead gap' in r for r in score.reasons)


# 12. Persistent structural trend remains valid across start boundary into [T1, T2]
@pytest.mark.asyncio
async def test_structural_trend_persists_across_contract_boundary():
    candles = make_test_candles(1, rsi_extreme=False)
    ticks = make_test_ticks(True)

    target = PredictionTarget(
        round_id='ROUND-PERSIST',
        target_start=datetime.now(timezone.utc) + timedelta(seconds=7),
        target_end=datetime.now(timezone.utc) + timedelta(seconds=12),
        lead_time_seconds=7.0,
        duration_seconds=5.0,
        scan_time=datetime.now(timezone.utc),
    )

    features = build_features(candles, ticks, target=target)
    assert features.impulse_exhaustion_risk is False
    assert features.trend_persistence_score == 2

    score = score_features(features)
    assert any('structural trend persistence confirmed' in r for r in score.reasons)

    decision = decide(score, min_score=3, min_margin=1, target=target)
    assert decision.direction == SignalDirection.UP
    assert decision.quality in {'VALID', 'STRONG'}


# 13. Unaligned temporal clock
@pytest.mark.asyncio
async def test_unaligned_temporal_clock_behavior(monkeypatch):
    service = SignalIntelligenceService()
    now = datetime.now(timezone.utc)

    mock_snapshot = MarketSnapshot(
        symbol='BTCUSDT', price=60500.0, event_time=now,
        provider='TEST', age_seconds=0.1, fresh=True, last_quantity=1.0, is_buyer_maker=False,
    )

    async def fake_get_snapshot(*args, **kwargs):
        return mock_snapshot

    async def fake_get_candles(*args, **kwargs):
        return make_test_candles(1)

    async def fake_get_ticks(*args, **kwargs):
        return make_test_ticks(True)

    monkeypatch.setattr('app.services.market_data.market_data_service.cache.get_snapshot', fake_get_snapshot)
    monkeypatch.setattr('app.services.market_data.market_data_service.get_cached_candles', fake_get_candles)
    monkeypatch.setattr('app.services.market_data.market_data_service.cache.get_recent_ticks', fake_get_ticks)

    # Calling scan without round_context or target marks temporal_alignment_valid as False
    res = await service.scan('BTCUSDT')
    assert res.temporal_alignment_valid is False
    assert res.target is None
