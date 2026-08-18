from app.core.config import Settings
from app.core.startup import validate_settings


def test_safe_defaults_are_valid():
    settings = Settings(_env_file=None)
    result = validate_settings(settings)
    assert result.ok is True
    assert settings.signal_mode == 'PAPER'
    assert settings.signals_enabled is False
    assert settings.default_pair == 'BTCUSDT'


def test_production_rejects_sqlite():
    settings = Settings(_env_file=None, app_env='production', database_url='sqlite:///./test.db')
    result = validate_settings(settings)
    assert result.ok is False
    assert any('PostgreSQL' in error for error in result.errors)


def test_invalid_expiry_fails():
    settings = Settings(_env_file=None, default_expiry_seconds=0)
    result = validate_settings(settings)
    assert result.ok is False
