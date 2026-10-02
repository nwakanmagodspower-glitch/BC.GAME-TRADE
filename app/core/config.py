from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'BCGAME TRADE'
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
    strategy_version: str = 'BTC_ORIGINAL_INTELLIGENCE_TIMER_V1'

    # Safe local/default mode is manual. Render production explicitly overrides
    # this to HYBRID_SYNC. Timing is a delivery concern and never changes scores.
    signal_timing_mode: str = 'MANUAL_SYNC'
    bcgame_round_sync_enabled: bool = False
    bcgame_round_sync_max_age_seconds: int = 2

    detrade_ws_enabled: bool = False
    detrade_ws_url: str = 'wss://websocket.detrade.com/ws'
    detrade_ws_token: str | None = None
    detrade_auth_mode: str = 'QUERY'
    detrade_origin: str = 'https://bc.game'
    detrade_user_agent: str = 'Mozilla/5.0'
    detrade_device: str = 'web-pc'
    detrade_client_type: int = 1
    detrade_subscription_cmd: str = '/contest/BTC/USD/5/ticker/subscribe'
    detrade_ticker_route: str = '/contest/BTC/USD/5/ticker'
    detrade_kline_subscription_cmd: str = '/kline/BTC-USD/ticker/subscribe'
    detrade_kline_route: str = '/kline/BTC-USD/ticker'
    detrade_kline_history_url: str = 'https://api.detrade.com/api/data/kline/history/ticker/latest'
    detrade_synthetic_symbol: str = 'BTC-USD'
    detrade_use_synthetic_feed: bool = True
    detrade_stake_room: str = '$1-$50'
    detrade_min_5s_range_dollars: float = 2.00
    detrade_max_5s_range_dollars: float = 25.00
    detrade_max_lead_impulse: float = 16.00
    detrade_up_min_margin: int = 5
    detrade_latency_safety_margin_ms: int = 0
    detrade_dispatch_min_remaining_ms: int = 0
    detrade_stale_after_ms: int = 1500
    detrade_probe_timeout_seconds: float = 2.5
    # User scans should not spend most of a short entry window waiting for a
    # background observer that is already expected to be connected. The longer
    # probe remains available to owner diagnostics.
    detrade_scan_probe_timeout_seconds: float = 1.0
    detrade_probe_coalesce_ms: int = 300
    detrade_ping_interval_seconds: float = 5.0
    detrade_ping_timeout_seconds: float = 10.0
    detrade_reconnect_seconds: float = 2.0
    detrade_reconnect_max_seconds: float = 30.0
    detrade_max_frame_bytes: int = 1_000_000

    # Calibrated Triple Confluence policy with Speed & Volatility Gate
    signal_min_score: int = 5
    signal_min_margin: int = 2
    signal_min_lead_range_dollars: float = 1.50
    signal_min_trade_count: int = 5
    signal_trade_flow_lookback_seconds: int = 15
    signal_settlement_window_seconds: int = 2
    signal_scan_coalesce_ms: int = 250
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
    market_trade_buffer_size: int = 50_000

    # BTC_MICROSTRUCTURE_V2 experimental settings
    microstructure_enabled: bool = False
    microstructure_book_max_age_seconds: float = 2.5
    microstructure_trade_max_age_seconds: float = 2.5
    microstructure_max_spread_bps: float = 3.0
    microstructure_min_l5_volume: float = 0.05
    microstructure_min_score: int = 7
    microstructure_min_margin: int = 4

    verification_max_deposit_proofs: int = 3
    verification_max_photo_bytes: int = 10_000_000
    verification_min_evidence_interval_seconds: float = 0.5
    verification_delivery_max_attempts: int = 5

    temporary_retention_days: int = 10
    cleanup_interval_seconds: int = 86400


@lru_cache
def get_settings() -> Settings:
    return Settings()
