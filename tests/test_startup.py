from app.core.config import Settings
from app.core.startup import validate_settings


def production(**overrides):
    values = dict(app_env='production', database_url='postgresql://user:pass@db/app', telegram_bot_token='token',
                  telegram_webhook_secret='1234567890abcdef', owner_telegram_id=1, admin_chat_id=2,
                  bcgame_registration_url='https://example.com/register', bcgame_deposit_url='https://example.com/deposit',
                  bcgame_updown_url='https://example.com/updown', support_url='https://example.com/support')
    values.update(overrides); return Settings(_env_file=None, **values)


def test_safe_defaults_are_valid():
    settings = Settings(_env_file=None); result = validate_settings(settings)
    assert result.ok is True; assert settings.signal_mode == 'PAPER'; assert settings.signals_enabled is False
    assert settings.broadcasts_enabled is False; assert settings.default_pair == 'BTCUSDT'; assert settings.default_product == 'BC_UPDOWN'


def test_safe_production_configuration_passes(): assert validate_settings(production()).ok

def test_production_rejects_sqlite(): assert not validate_settings(production(database_url='sqlite:///bad.db')).ok

def test_signals_cannot_enable_in_paper_mode(): assert not validate_settings(production(signals_enabled=True, signal_mode='PAPER')).ok

def test_v1_pair_and_product_are_locked():
    assert not validate_settings(production(default_pair='ETHUSDT')).ok
    assert not validate_settings(production(default_product='FUTURES')).ok

def test_v1_expiry_is_locked(): assert not validate_settings(Settings(_env_file=None, default_expiry_seconds=60)).ok

def test_missing_production_secret_fails(): assert not validate_settings(production(telegram_webhook_secret=None)).ok

def test_short_webhook_secret_fails(): assert not validate_settings(production(telegram_webhook_secret='short')).ok
