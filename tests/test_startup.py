from app.core.config import Settings
from app.core.startup import validate_settings


def production(**overrides):
    values = dict(
        app_env='production',
        database_url='postgresql://user:pass@db/app',
        telegram_bot_token='token',
        telegram_webhook_secret='1234567890abcdef',
        owner_telegram_id=1,
        bcgame_registration_url='https://example.com/register',
        bcgame_deposit_url='https://example.com/deposit',
        bcgame_updown_url='https://bc.game/trading/up-down',
        support_url='https://example.com/support',
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_safe_defaults_are_valid():
    settings = Settings(_env_file=None)
    result = validate_settings(settings)
    assert result.ok is True
    assert settings.signal_mode == 'PAPER'
    assert settings.signals_enabled is False
    assert settings.broadcasts_enabled is False
    assert settings.game_market == 'BTC/USD'
    assert settings.analysis_pair == 'BTCUSDT'
    assert settings.default_product == 'BC_UPDOWN_5S'
    assert settings.default_expiry_seconds == 5
    assert settings.default_stake_band == '1-50'
    assert settings.bcgame_round_sync_enabled is False


def test_safe_production_configuration_passes():
    assert validate_settings(production()).ok


def test_production_rejects_sqlite():
    assert not validate_settings(production(database_url='sqlite:///bad.db')).ok


def test_signals_cannot_enable_in_paper_mode():
    assert not validate_settings(production(signals_enabled=True, signal_mode='PAPER')).ok


def test_live_requires_round_sync_enabled():
    assert not validate_settings(production(signal_mode='LIVE', bcgame_round_sync_enabled=False)).ok
    assert validate_settings(production(signal_mode='LIVE', bcgame_round_sync_enabled=True)).ok


def test_v1_product_contract_is_locked():
    assert not validate_settings(production(game_market='ETH/USD')).ok
    assert not validate_settings(production(analysis_pair='ETHUSDT')).ok
    assert not validate_settings(production(default_product='BC_UPDOWN')).ok
    assert not validate_settings(production(default_expiry_seconds=300)).ok
    assert not validate_settings(production(default_stake_band='50-100')).ok


def test_action_window_is_bounded():
    assert not validate_settings(production(signal_minimum_action_lead_seconds=10, signal_maximum_action_lead_seconds=5)).ok


def test_missing_production_secret_fails():
    assert not validate_settings(production(telegram_webhook_secret=None)).ok


def test_missing_owner_id_fails():
    assert not validate_settings(production(owner_telegram_id=None)).ok


def test_short_webhook_secret_fails():
    assert not validate_settings(production(telegram_webhook_secret='short')).ok
