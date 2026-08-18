from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'BC.GAME TRADE'
    app_env: str = 'development'
    database_url: str = 'sqlite:///./bcgame_trade.db'
    run_background_jobs: bool = False

    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    owner_telegram_id: int | None = None

    bcgame_registration_url: str | None = None
    bcgame_deposit_url: str | None = None
    bcgame_updown_url: str | None = None
    support_url: str | None = None

    signal_mode: str = 'PAPER'
    signals_enabled: bool = False
    broadcasts_enabled: bool = False

    # Product contract: BC.GAME displays BTC/USD. Binance BTCUSDT remains the
    # initial external analysis symbol only; it is never treated as BC.GAME
    # settlement truth.
    game_market: str = 'BTC/USD'
    analysis_pair: str = 'BTCUSDT'
    default_pair: str = 'BTCUSDT'  # compatibility alias for existing services
    default_product: str = 'BC_UPDOWN_5S'
    default_expiry_seconds: int = 5
    default_stake_band: str = '1-50'
    strategy_version: str = 'BTC_UPDOWN_5S_V1.0'

    # Round synchronization must be connected and healthy before LIVE
    # actionable signals are allowed. PAPER may be used for external-reference
    # research while this remains false.
    bcgame_round_sync_enabled: bool = False
    bcgame_round_sync_max_age_seconds: int = 2
    signal_minimum_action_lead_seconds: int = 5

    signal_min_score: int = 6
    signal_min_margin: int = 3
    signal_trade_flow_lookback_seconds: int = 15
    signal_settlement_window_seconds: int = 2
    worker_heartbeat_max_age_seconds: int = 30

    market_data_provider: str = 'BINANCE_SPOT'
    market_data_rest_base_url: str = 'https://api.binance.com'
    market_data_ws_base_url: str = 'wss://stream.binance.com:9443/ws'
    market_data_max_age_seconds: int = 2
    market_data_reconnect_seconds: int = 3
    market_data_kline_limit: int = 120

    temporary_retention_days: int = 10
    cleanup_interval_seconds: int = 86400


@lru_cache
def get_settings() -> Settings:
    return Settings()
