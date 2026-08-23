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
    assert settings.signal_timing_mode == 'MANUAL_SYNC'
    assert settings.game_market == 'BTC/USD'
    assert settings.analysis_pair == 'BTCUSDT'
    assert settings.default_product == 'BC_UPDOWN_5S'
    assert settings.default_expiry_seconds == 5
    assert settings.default_stake_band == '1-50'
    assert settings.strategy_version == 'BTC_ORIGINAL_INTELLIGENCE_TIMER_V1'
    assert settings.signal_min_score == 6
    assert settings.signal_min_margin == 3


def test_safe_production_configuration_passes():
    assert validate_settings(production()).ok


def test_original_strategy_identity_and_thresholds_are_locked():
    assert not validate_settings(production(strategy_version='BTC_UPDOWN_5S_V1.4.2')).ok
    assert not validate_settings(production(signal_min_score=8)).ok
    assert not validate_settings(production(signal_min_margin=4)).ok
    assert validate_settings(production(signal_min_score=6, signal_min_margin=3)).ok


def test_live_manual_sync_is_allowed():
    assert validate_settings(production(signal_mode='LIVE', signals_enabled=True, signal_timing_mode='MANUAL_SYNC', bcgame_round_sync_enabled=False)).ok


def test_hybrid_and_auto_sync_require_round_sync_switch():
    assert not validate_settings(production(signal_timing_mode='HYBRID_SYNC', bcgame_round_sync_enabled=False)).ok
    assert validate_settings(production(signal_timing_mode='HYBRID_SYNC', bcgame_round_sync_enabled=True)).ok
    assert not validate_settings(production(signal_timing_mode='AUTO_SYNC', bcgame_round_sync_enabled=False)).ok
    assert validate_settings(production(
        signal_timing_mode='AUTO_SYNC',
        bcgame_round_sync_enabled=True,
        detrade_ws_enabled=True,
        detrade_ws_token='ephemeral-secret',
    )).ok


def test_hybrid_allows_missing_detrade_token_but_auto_requires_it():
    hybrid = validate_settings(production(
        signal_timing_mode='HYBRID_SYNC',
        bcgame_round_sync_enabled=True,
        detrade_ws_enabled=True,
        detrade_ws_token=None,
    ))
    assert hybrid.ok
    assert any('manual Scan Now fallback' in warning for warning in hybrid.warnings)

    assert not validate_settings(production(
        signal_timing_mode='AUTO_SYNC',
        bcgame_round_sync_enabled=True,
        detrade_ws_enabled=True,
        detrade_ws_token=None,
    )).ok

    assert validate_settings(production(
        signal_timing_mode='HYBRID_SYNC',
        bcgame_round_sync_enabled=True,
        detrade_ws_enabled=True,
        detrade_ws_token='ephemeral-secret',
    )).ok


def test_placeholder_token_is_missing_and_auto_sync_fails_closed():
    hybrid = validate_settings(production(
        signal_timing_mode='HYBRID_SYNC',
        bcgame_round_sync_enabled=True,
        detrade_ws_enabled=True,
        detrade_ws_token='temporary',
    ))
    assert hybrid.ok
    assert any('no usable token' in warning for warning in hybrid.warnings)

    automatic = validate_settings(production(
        signal_timing_mode='AUTO_SYNC',
        bcgame_round_sync_enabled=True,
        detrade_ws_enabled=True,
        detrade_ws_token='temporary',
    ))
    assert not automatic.ok


def test_detrade_verified_route_and_safety_values_are_validated():
    assert not validate_settings(production(
        detrade_ws_enabled=True,
        detrade_ws_token='secret',
        detrade_subscription_cmd='/wrong/route',
    )).ok
    assert not validate_settings(production(
        detrade_ws_enabled=True,
        detrade_ws_token='secret',
        detrade_probe_timeout_seconds=0,
    )).ok


def test_production_rejects_sqlite():
    assert not validate_settings(production(database_url='sqlite:///bad.db')).ok


def test_signals_cannot_enable_in_paper_mode():
    assert not validate_settings(production(signals_enabled=True, signal_mode='PAPER')).ok


def test_v1_product_contract_is_locked():
    assert not validate_settings(production(game_market='ETH/USD')).ok
    assert not validate_settings(production(analysis_pair='ETHUSDT')).ok
    assert not validate_settings(production(default_product='BC_UPDOWN')).ok
    assert not validate_settings(production(default_expiry_seconds=300)).ok
    assert not validate_settings(production(default_stake_band='50-100')).ok


def test_missing_production_secret_fails():
    assert not validate_settings(production(telegram_webhook_secret=None)).ok


def test_missing_owner_id_fails():
    assert not validate_settings(production(owner_telegram_id=None)).ok


def test_short_webhook_secret_fails():
    assert not validate_settings(production(telegram_webhook_secret='short')).ok


def test_production_rejects_unsafe_market_origins_and_wrong_game_url():
    assert not validate_settings(production(market_data_rest_base_url='http://api.binance.com')).ok
    assert not validate_settings(production(market_data_ws_base_url='ws://stream.binance.com/ws')).ok
    assert not validate_settings(production(market_data_rest_base_url='https://example.com')).ok
    assert not validate_settings(production(bcgame_updown_url='https://example.com/trading/up-down')).ok
