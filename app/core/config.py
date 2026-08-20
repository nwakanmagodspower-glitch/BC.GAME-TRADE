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
    telegram_webhook_max_body_bytes: int = 1_000_000
    telegram_update_processing_timeout_seconds: int = 60
    telegram_webhook_max_concurrency: int = 32
    telegram_webhook_queue_timeout_seconds: float = 0.25
    telegram_user_update_limit: int = 30
    telegram_user_update_window_seconds: float = 10.0

    bcgame_registration_url: str | None = None
    bcgame_deposit_url: str | None = None
    bcgame_updown_url: str | None = None
    support_url: str | None = None

    signal_mode: str = 'PAPER'
    signals_enabled: bool = False
    broadcasts_enabled: bool = False

    game_market: str = 'BTC/USD'
    analysis_pair: str = 'BTCUSDT'
    default_pair: str = 'BTCUSDT'
    default_product: str = 'BC_UPDOWN_5S'
    default_expiry_seconds: int = 5
    default_stake_band: str = '1-50'
    strategy_version: str = 'BTC_UPDOWN_5S_V1.1'

    signal_timing_mode: str = 'MANUAL_SYNC'
    manual_sync_allowed_countdowns: str = '15,14,13,12'
    manual_sync_min_remaining_after_scan: float = 7.0
    bcgame_round_sync_enabled: bool = False
    bcgame_round_sync_max_age_seconds: int = 2

    signal_min_score: int = 6
    signal_min_margin: int = 3
    signal_trade_flow_lookback_seconds: int = 15
    signal_min_recent_trades: int = 12
    signal_min_tick_span_seconds: float = 4.0
    signal_settlement_window_seconds: int = 2
    signal_scan_coalesce_ms: int = 750
    signal_user_cooldown_seconds: float = 5.0
    worker_heartbeat_max_age_seconds: int = 30

    market_data_provider: str = 'BINANCE_SPOT'
    market_data_rest_base_url: str = 'https://api.binance.com'
    market_data_ws_base_url: str = 'wss://stream.binance.com:9443/ws'
    market_data_max_age_seconds: int = 2
    market_data_reconnect_seconds: int = 3
    market_data_kline_limit: int = 120
    market_data_rest_max_response_bytes: int = 1_000_000
    market_candle_refresh_seconds: int = 15
    market_candle_max_age_seconds: int = 60
    market_data_future_skew_seconds: float = 2.0

    verification_max_deposit_proofs: int = 3
    verification_max_photo_bytes: int = 10_000_000
    verification_min_evidence_interval_seconds: float = 0.5
    verification_delivery_max_attempts: int = 5

    temporary_retention_days: int = 10
    cleanup_interval_seconds: int = 86400

    def manual_countdowns(self) -> tuple[int, ...]:
        values: list[int] = []
        for raw in self.manual_sync_allowed_countdowns.split(','):
            raw = raw.strip()
            if raw:
                values.append(int(raw))
        return tuple(values)


@lru_cache
def get_settings() -> Settings:
    return Settings()
