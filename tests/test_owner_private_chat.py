from types import SimpleNamespace

from app.bot import admin_handlers


def test_owner_controls_require_matching_private_chat(monkeypatch):
    monkeypatch.setattr(admin_handlers.settings, 'owner_telegram_id', 12345)

    private = SimpleNamespace(
        effective_user=SimpleNamespace(id=12345),
        effective_chat=SimpleNamespace(id=12345, type='private'),
    )
    group = SimpleNamespace(
        effective_user=SimpleNamespace(id=12345),
        effective_chat=SimpleNamespace(id=-100999, type='supergroup'),
    )
    wrong_private = SimpleNamespace(
        effective_user=SimpleNamespace(id=54321),
        effective_chat=SimpleNamespace(id=54321, type='private'),
    )

    assert admin_handlers._is_owner(private) is True
    assert admin_handlers._is_owner(group) is False
    assert admin_handlers._is_owner(wrong_private) is False
