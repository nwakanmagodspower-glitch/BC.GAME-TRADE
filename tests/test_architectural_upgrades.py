import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.bot import handlers, signal_views
from app.core.database import Base
from app.models.entities import OnboardingStep, Signal, SignalDirection, SignalStatus, User, UserStatus
from app.services.channel_broadcaster import ChannelLiveBroadcaster
from app.services.lead_funnel_scheduler import LeadFunnelScheduler
from app.services.onboarding import OnboardingService
from app.services.user_signals import UserSignalService
from app.signals.microstructure.decision import decide_microstructure
from app.signals.microstructure.features import MicrostructureFeatureSnapshot
from app.signals.microstructure.scoring import score_microstructure_features
from tests.test_microstructure_scoring import create_feature_snapshot


def make_test_db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


# ==========================================
# TASK 1: Lead Drop-off & Channel Gate Tests
# ==========================================

def test_user_funnel_step_and_fbclid_initialization():
    db = make_test_db()
    service = OnboardingService(db)
    tg_user = SimpleNamespace(id=111, username='lead1', first_name='LeadOne')

    # 1. Create user with fbclid
    user = service.get_or_create_user(tg_user, fbclid='fb.1.12345678')
    assert user.funnel_step == '1_STARTED'
    assert user.fbclid == 'fb.1.12345678'
    assert user.step_updated_at is not None
    assert user.consecutive_wins == 0

    # 2. Advance to 2_CHANNEL_JOINED
    service.set_funnel_step(user, '2_CHANNEL_JOINED')
    assert user.funnel_step == '2_CHANNEL_JOINED'

    # 3. Enter BCGAME User ID -> advances to 3_UID_SUBMITTED
    service.set_bcgame_user_id(user, '98765432')
    assert user.funnel_step == '3_UID_SUBMITTED'

    # 4. Review & approve -> advances to 4_VIP_APPROVED
    service.set_profile_proof(user, 'profile_file_id')
    service.add_deposit_proof(user, 'deposit_file_id')
    req = service.submit(user)

    # Simulate packet delivery
    from app.models.entities import VerificationDelivery, VerificationDeliveryStatus
    deliv = db.scalar(select(VerificationDelivery).where(VerificationDelivery.verification_request_id == req.id))
    deliv.status = VerificationDeliveryStatus.SENT
    db.commit()

    _, approved_user, _ = service.review(req.id, admin_id=999, action='approve')
    assert approved_user.funnel_step == '4_VIP_APPROVED'


@pytest.mark.asyncio
async def test_start_captures_fbclid_from_payload(monkeypatch):
    db = make_test_db()
    session_factory = sessionmaker(bind=db.bind)
    monkeypatch.setattr(handlers, 'SessionLocal', session_factory)
    monkeypatch.setattr(handlers.settings, 'telegram_channel_id', None)  # Gate open

    class DummyChat:
        def __init__(self):
            self.messages = []
            self.videos = []
        async def send_message(self, text, reply_markup=None, **kwargs):
            self.messages.append(text)
        async def send_video(self, video, caption=None, **kwargs):
            self.videos.append(video)

    chat = DummyChat()
    tg_user = SimpleNamespace(id=222, username='lead2', first_name='LeadTwo')
    update = SimpleNamespace(effective_user=tg_user, effective_chat=chat)
    context = SimpleNamespace(args=['fbclid_AbCdEf123456'])

    await handlers.start(update, context)
    saved_user = db.scalar(select(User).where(User.telegram_user_id == 222))
    assert saved_user is not None
    assert saved_user.fbclid == 'AbCdEf123456'


@pytest.mark.asyncio
async def test_channel_gate_blocks_non_members(monkeypatch):
    db = make_test_db()
    session_factory = sessionmaker(bind=db.bind)
    monkeypatch.setattr(handlers, 'SessionLocal', session_factory)
    monkeypatch.setattr(handlers.settings, 'telegram_channel_id', '-1009999999')
    monkeypatch.setattr(handlers.settings, 'telegram_channel_invite_link', 'https://t.me/testvip')

    class MockBot:
        async def get_chat_member(self, chat_id, user_id):
            return SimpleNamespace(status='left')

    class DummyChat:
        def __init__(self):
            self.messages = []
            self.markups = []
        async def send_message(self, text, reply_markup=None, **kwargs):
            self.messages.append(text)
            self.markups.append(reply_markup)

    chat = DummyChat()
    tg_user = SimpleNamespace(id=333, username='lead3', first_name='LeadThree')
    update = SimpleNamespace(effective_user=tg_user, effective_chat=chat)
    context = SimpleNamespace(args=[], bot=MockBot())

    await handlers.start(update, context)
    assert len(chat.messages) == 1
    assert 'Terminal Locked — Join Official VIP Channel to Unlock' in chat.messages[0]
    # Verify only single join channel button exists (no verify button)
    markup = chat.markups[0]
    assert len(markup.inline_keyboard) == 1
    assert len(markup.inline_keyboard[0]) == 1
    assert markup.inline_keyboard[0][0].text == '📢 Join Official VIP Channel'


@pytest.mark.asyncio
async def test_chat_member_update_auto_unlocks_on_join(monkeypatch):
    db = make_test_db()
    session_factory = sessionmaker(bind=db.bind)
    monkeypatch.setattr(handlers, 'SessionLocal', session_factory)
    monkeypatch.setattr(handlers.settings, 'telegram_channel_id', '-1009999999')

    sent_messages = []
    class MockBot:
        async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
            sent_messages.append((chat_id, text, reply_markup))

    tg_user = SimpleNamespace(id=444, username='lead4', first_name='LeadFour', is_bot=False)
    update = SimpleNamespace(
        chat_member=SimpleNamespace(
            chat=SimpleNamespace(id=-1009999999, username='testchannel'),
            old_chat_member=SimpleNamespace(status='left'),
            new_chat_member=SimpleNamespace(status='member', user=tg_user),
        )
    )
    context = SimpleNamespace(bot=MockBot())

    await handlers.chat_member_update(update, context)

    # User in DB should now be 2_CHANNEL_JOINED
    saved_user = db.scalar(select(User).where(User.telegram_user_id == 444))
    assert saved_user is not None
    assert saved_user.funnel_step == '2_CHANNEL_JOINED'
    # And initial wonderful onboarding welcome was sent directly to private chat
    assert len(sent_messages) >= 1
    assert sent_messages[0][0] == 444
    assert 'Welcome LeadFour!' in sent_messages[0][1]
    assert '₦10,000 to ₦20,000+' in sent_messages[0][1]
    # Keyboards include Create Free Account and I Have Registered
    buttons = [b.text for row in sent_messages[0][2].inline_keyboard for b in row]
    assert '✅ I Have Registered' in buttons


@pytest.mark.asyncio
async def test_lead_funnel_scheduler_sends_reminders(monkeypatch):
    db = make_test_db()
    session_factory = sessionmaker(bind=db.bind)
    monkeypatch.setattr('app.services.lead_funnel_scheduler.SessionLocal', session_factory)

    now = datetime.now(timezone.utc)
    # Lead 1: started 40 mins ago
    u1 = User(telegram_user_id=1001, first_name='U1', funnel_step='1_STARTED', step_updated_at=now - timedelta(minutes=40))
    # Lead 2: channel joined 5 hours ago
    u2 = User(telegram_user_id=1002, first_name='U2', funnel_step='2_CHANNEL_JOINED', step_updated_at=now - timedelta(hours=5))
    # Lead 3: uid submitted 20 hours ago
    u3 = User(telegram_user_id=1003, first_name='U3', funnel_step='3_UID_SUBMITTED', step_updated_at=now - timedelta(hours=20))
    db.add_all([u1, u2, u3])
    db.commit()

    reminders_sent = []
    class MockBot:
        async def send_message(self, chat_id, text, **kwargs):
            reminders_sent.append((chat_id, text))

    scheduler = LeadFunnelScheduler()
    count = await scheduler.check_and_send_reminders(MockBot())
    assert count == 3
    assert len(reminders_sent) == 3

    # Running a second time should not spam because last_reminded_step was set
    count2 = await scheduler.check_and_send_reminders(MockBot())
    assert count2 == 0


# ==========================================
# TASK 2: 15-Second Channel Live Countdown
# ==========================================

@pytest.mark.asyncio
async def test_channel_live_broadcaster_sequence(monkeypatch):
    monkeypatch.setattr('app.services.channel_broadcaster.settings.analysis_pair', 'BTCUSDT')

    async def mock_sleep(s):
        pass
    monkeypatch.setattr(asyncio, 'sleep', mock_sleep)

    from app.services.market_data import MarketSnapshot
    async def mock_get_snapshot(*args, **kwargs):
        return MarketSnapshot(
            symbol='BTCUSDT',
            price=95100.0,
            event_time=datetime.now(timezone.utc),
            provider='BINANCE_SPOT',
            age_seconds=0.1,
            fresh=True,
            last_quantity=1.0,
            is_buyer_maker=False,
        )
    monkeypatch.setattr('app.services.market_data.market_data_service.cache.get_snapshot', mock_get_snapshot)

    messages = []
    edits = []

    class MockBot:
        async def get_me(self):
            return SimpleNamespace(username='bcgame_bot')
        async def send_message(self, chat_id, text, **kwargs):
            msg = SimpleNamespace(message_id=999, text=text)
            messages.append(text)
            return msg
        async def edit_message_text(self, chat_id, message_id, text, **kwargs):
            edits.append(text)

    broadcaster = ChannelLiveBroadcaster()
    success = await broadcaster.broadcast_live_round(
        bot=MockBot(),
        channel_id='@testchannel',
        direction=SignalDirection.UP,
        entry_price=95000.0,
    )

    assert success is True
    # 1 initial message sent
    assert len(messages) == 1
    assert '📡 AGENTIC AI — LIVE ROUND' in messages[0]
    assert 'Countdown: 15s' in messages[0]
    assert 'Entry: $95,000.00' in messages[0]

    # 2 edits performed (5s countdown and final round finish)
    assert len(edits) == 2
    assert 'Locking Result In: 5 Seconds...' in edits[0]
    assert '✅ ROUND FINISHED — UP WON!' in edits[1]
    assert 'Session Streak: 1 WINS' in edits[1]
    assert broadcaster.session_streak == 1


# ==========================================
# TASK 3: Micro-Chop Filter & Discipline
# ==========================================

def test_micro_chop_flat_market_filter_returns_hold_signal():
    features = MicrostructureFeatureSnapshot(
        **{
            **create_feature_snapshot().to_dict(),
            "range_20s": 0.35,
            "lead_range_dollars": 0.30,
            "bar_5s_range": 0.20,
            "regime_classification": "NEUTRAL_CHOP",
        }
    )
    score = score_microstructure_features(features, is_synthetic=True)
    decision = decide_microstructure(score, features, is_synthetic=True, min_5s_range=1.50)

    assert decision.direction == SignalDirection.NO_TRADE
    assert 'HOLD / CHOP DETECTED' in decision.reason
    assert decision.quality == 'HOLD / CHOP DETECTED'

    # Check signal views formatting
    sig = Signal(
        direction=SignalDirection.NO_TRADE,
        status=SignalStatus.NO_TRADE,
        status_reason=decision.reason,
        features_snapshot={'_decision': {'quality': 'HOLD / CHOP DETECTED'}},
    )
    formatted = signal_views.format_signal(sig)
    assert '⏸️ HOLD / CHOP DETECTED' in formatted
    assert 'AI Capital Protection: Active' in formatted
    assert 'waiting 10 seconds for a clean breakout impulse' in formatted


@pytest.mark.asyncio
async def test_3_win_session_discipline_tracker(monkeypatch):
    db = make_test_db()
    session_factory = sessionmaker(bind=db.bind)
    monkeypatch.setattr(handlers, 'SessionLocal', session_factory)
    monkeypatch.setattr('app.services.user_signals.settings.signal_mode', 'LIVE')
    monkeypatch.setattr('app.services.user_signals.settings.signals_enabled', True)
    monkeypatch.setattr(handlers.settings, 'session_discipline_cooldown_minutes', 15)
    monkeypatch.setattr('app.services.user_signals.settings.session_discipline_cooldown_minutes', 15)

    user = User(
        telegram_user_id=555,
        status=UserStatus.APPROVED,
        funnel_step='4_VIP_APPROVED',
        consecutive_wins=0,
    )
    db.add(user)
    db.commit()

    # User records win 1
    query1 = SimpleNamespace(
        from_user=SimpleNamespace(id=555),
        data='discipline:win:1',
        answer=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    await handlers.session_discipline_callback(SimpleNamespace(callback_query=query1), SimpleNamespace())
    db.refresh(user)
    assert user.consecutive_wins == 1
    assert user.session_cooldown_until is None

    # User records win 2
    query2 = SimpleNamespace(
        from_user=SimpleNamespace(id=555),
        data='discipline:win:2',
        answer=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    await handlers.session_discipline_callback(SimpleNamespace(callback_query=query2), SimpleNamespace())
    db.refresh(user)
    assert user.consecutive_wins == 2

    # User records win 3 -> triggers 15-minute discipline cooldown!
    query3 = SimpleNamespace(
        from_user=SimpleNamespace(id=555),
        data='discipline:win:3',
        answer=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    await handlers.session_discipline_callback(SimpleNamespace(callback_query=query3), SimpleNamespace())
    db.refresh(user)
    assert user.session_cooldown_until is not None
    cooldown = user.session_cooldown_until.replace(tzinfo=timezone.utc) if user.session_cooldown_until.tzinfo is None else user.session_cooldown_until
    assert cooldown > datetime.now(timezone.utc)

    # When user attempts to scan while cooldown is active: blocked by AI discipline protection
    service = UserSignalService(db)
    res = await service.request_scan(user.id)
    assert res.available is False
    assert '3-WIN SESSION DISCIPLINE COOLDOWN ACTIVE' in res.reason
    assert '15-minute cooldown' in res.reason


@pytest.mark.asyncio
async def test_no_cooldown_by_default(monkeypatch):
    db = make_test_db()
    session_factory = sessionmaker(bind=db.bind)
    monkeypatch.setattr(handlers, 'SessionLocal', session_factory)
    monkeypatch.setattr('app.services.user_signals.settings.signal_mode', 'LIVE')
    monkeypatch.setattr('app.services.user_signals.settings.signals_enabled', True)

    user = User(
        telegram_user_id=777,
        status=UserStatus.APPROVED,
        funnel_step='4_VIP_APPROVED',
        consecutive_wins=2,
    )
    db.add(user)
    db.commit()

    query = SimpleNamespace(
        from_user=SimpleNamespace(id=777),
        data='discipline:win:10',
        answer=AsyncMock(),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )
    await handlers.session_discipline_callback(SimpleNamespace(callback_query=query), SimpleNamespace())
    db.refresh(user)
    # Consecutive wins reset, but NO cooldown is set!
    assert user.consecutive_wins == 0
    assert user.session_cooldown_until is None
    # User message confirms terminal remains unlocked
    query.message.reply_text.assert_called_once()
    msg = query.message.reply_text.call_args[0][0]
    assert 'Your terminal remains 100% unlocked' in msg

