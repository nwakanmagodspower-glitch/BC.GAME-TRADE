from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.bot import admin_handlers
from app.bot.admin_handlers import (
    _admin_menu, clear_welcome_video_command, set_welcome_video_command,
)
from app.core.database import Base
from app.services.admin_ops import AdminOpsService


def test_admin_menu_offers_disable_when_signals_on():
    markup = _admin_menu(True)
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]
    assert 'adminops:signals:off' in callbacks
    assert 'adminops:signals:on' not in callbacks


def test_admin_menu_offers_enable_when_signals_off():
    markup = _admin_menu(False)
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]
    assert 'adminops:signals:on' in callbacks
    assert 'adminops:signals:off' not in callbacks


def test_admin_ops_runtime_settings():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        service = AdminOpsService(session)
        assert service.get_setting('non_existent', 'default_val') == 'default_val'

        service.set_setting(AdminOpsService.WELCOME_VIDEO_KEY, 'test_file_id_123', actor_telegram_id=999)
        assert service.get_setting(AdminOpsService.WELCOME_VIDEO_KEY) == 'test_file_id_123'

        service.set_setting(AdminOpsService.WELCOME_VIDEO_KEY, None, actor_telegram_id=999)
        assert service.get_setting(AdminOpsService.WELCOME_VIDEO_KEY) is None
    finally:
        session.close()


class DummyMessage:
    def __init__(self):
        self.video = None
        self.reply_to_message = None
        self.animation = None
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class DummyChat:
    type = 'private'
    id = 12345

    def __init__(self):
        self.messages = []

    async def send_message(self, text, **kwargs):
        self.messages.append(text)


@pytest.mark.asyncio
async def test_set_and_clear_welcome_video_commands(monkeypatch):
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    monkeypatch.setattr(admin_handlers.settings, 'owner_telegram_id', 12345)
    monkeypatch.setattr(admin_handlers, 'SessionLocal', session_factory)

    chat = DummyChat()
    user = SimpleNamespace(id=12345)

    # 1. Non-owner is ignored silently
    non_owner_msg = DummyMessage()
    non_owner_update = SimpleNamespace(
        effective_user=SimpleNamespace(id=99999),
        effective_chat=SimpleNamespace(id=99999, type='private'),
        message=non_owner_msg,
    )
    context = SimpleNamespace(args=['https://example.com/demo.mp4'])
    await set_welcome_video_command(non_owner_update, context)
    assert len(non_owner_msg.replies) == 0

    # 2. Owner sets video via arg
    owner_msg = DummyMessage()
    owner_update = SimpleNamespace(
        effective_user=user,
        effective_chat=chat,
        message=owner_msg,
    )
    await set_welcome_video_command(owner_update, context)
    assert any('Welcome video updated' in m for m in owner_msg.replies)

    # Verify setting in DB
    with session_factory() as db:
        service = AdminOpsService(db)
        assert service.get_setting(AdminOpsService.WELCOME_VIDEO_KEY) == 'https://example.com/demo.mp4'

    # 3. Owner clears video
    owner_clear_msg = DummyMessage()
    owner_clear_update = SimpleNamespace(
        effective_user=user,
        effective_chat=chat,
        message=owner_clear_msg,
    )
    await clear_welcome_video_command(owner_clear_update, context)
    assert any('removed' in m for m in owner_clear_msg.replies)

    # Verify setting cleared in DB
    with session_factory() as db:
        service = AdminOpsService(db)
        assert service.get_setting(AdminOpsService.WELCOME_VIDEO_KEY) is None


@pytest.mark.asyncio
async def test_start_delivers_welcome_video_and_reassurance(monkeypatch):
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    from app.bot import handlers
    monkeypatch.setattr(handlers, 'SessionLocal', session_factory)

    class VideoChat:
        def __init__(self):
            self.videos = []
            self.messages = []

        async def send_video(self, video, caption=None, **kwargs):
            self.videos.append((video, caption))

        async def send_message(self, text, reply_markup=None, **kwargs):
            self.messages.append((text, reply_markup))

    chat = VideoChat()
    tg_user = SimpleNamespace(id=777, username='trader777', first_name='Trader')
    update = SimpleNamespace(effective_user=tg_user, effective_chat=chat)
    context = SimpleNamespace()

    # 1. First run without video set
    await handlers.start(update, context)
    assert len(chat.videos) == 0
    assert len(chat.messages) == 1
    text, markup = chat.messages[0]
    assert '100% FREE ACCESS' in text
    assert 'Your deposit remains 100% in YOUR personal BCGAME wallet' in text

    # 2. Set video in DB and test with new user
    with session_factory() as db:
        AdminOpsService(db).set_setting(AdminOpsService.WELCOME_VIDEO_KEY, 'video_file_id_999', actor_telegram_id=123)

    chat2 = VideoChat()
    tg_user2 = SimpleNamespace(id=888, username='trader888', first_name='Trader2')
    update2 = SimpleNamespace(effective_user=tg_user2, effective_chat=chat2)
    await handlers.start(update2, context)
    assert len(chat2.videos) == 1
    assert chat2.videos[0][0] == 'video_file_id_999'
    assert 'Watch this live demonstration' in chat2.videos[0][1]
    assert len(chat2.messages) == 1
    assert '100% FREE ACCESS' in chat2.messages[0][0]


@pytest.mark.asyncio
async def test_approve_command_and_vip_deep_link(monkeypatch):
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    from app.bot import admin_handlers, handlers
    monkeypatch.setattr(admin_handlers.settings, 'owner_telegram_id', 12345)
    monkeypatch.setattr(admin_handlers, 'SessionLocal', session_factory)
    monkeypatch.setattr(handlers, 'SessionLocal', session_factory)

    # 1. Owner uses /approve on a new lead ID
    chat = DummyChat()
    msg = DummyMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=12345),
        effective_chat=chat,
        message=msg,
    )
    context = SimpleNamespace(args=['555123'])
    await admin_handlers.approve_command(update, context)
    assert any('APPROVED INSTANTLY' in r for r in msg.replies)

    # 2. When that lead types /start, they are immediately approved!
    lead_chat = DummyChat()
    lead_update = SimpleNamespace(
        effective_user=SimpleNamespace(id=555123, username='vip_lead', first_name='VIP'),
        effective_chat=lead_chat,
    )
    lead_context = SimpleNamespace(args=[])
    await handlers.start(lead_update, lead_context)
    assert any('Access active' in m for m in lead_chat.messages)

    # 3. Test VIP referral link (?start=vip)
    direct_chat = DummyChat()
    direct_update = SimpleNamespace(
        effective_user=SimpleNamespace(id=999888, username='direct_lead', first_name='DirectVIP'),
        effective_chat=direct_chat,
    )
    direct_context = SimpleNamespace(args=['vip'])
    await handlers.start(direct_update, direct_context)
    assert any('VIP ACCESS' in m for m in direct_chat.messages)
    assert any('Access active' in m for m in direct_chat.messages)
