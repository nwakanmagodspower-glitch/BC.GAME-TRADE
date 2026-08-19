from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.config import Settings


@dataclass(frozen=True)
class StartupCheck:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _valid_https_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == 'https'
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _valid_provider_url(value: str, schemes: set[str]) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme in schemes
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def validate_settings(settings: Settings) -> StartupCheck:
    errors: list[str] = []
    warnings: list[str] = []
    mode = settings.signal_mode.upper()
    timing_mode = settings.signal_timing_mode.upper()

    if mode not in {'PAPER', 'LIVE'}: errors.append('SIGNAL_MODE must be PAPER or LIVE')
    if timing_mode not in {'MANUAL_SYNC', 'AUTO_SYNC'}: errors.append('SIGNAL_TIMING_MODE must be MANUAL_SYNC or AUTO_SYNC')
    if settings.game_market.upper() != 'BTC/USD': errors.append('V1 requires GAME_MARKET=BTC/USD')
    if settings.analysis_pair.upper() != 'BTCUSDT' or settings.default_pair.upper() != 'BTCUSDT': errors.append('V1 analysis feed requires BTCUSDT')
    if settings.default_product.upper() != 'BC_UPDOWN_5S': errors.append('V1 requires DEFAULT_PRODUCT=BC_UPDOWN_5S')
    if settings.default_expiry_seconds != 5: errors.append('V1 requires DEFAULT_EXPIRY_SECONDS=5')
    if settings.default_stake_band != '1-50': errors.append('V1 requires DEFAULT_STAKE_BAND=1-50')
    if not settings.strategy_version.startswith('BTC_UPDOWN_5S_V1'): errors.append('V1 strategy identity must remain BTC_UPDOWN_5S_V1.x')
    if settings.market_data_max_age_seconds <= 0: errors.append('MARKET_DATA_MAX_AGE_SECONDS must be greater than zero')
    if settings.market_candle_refresh_seconds <= 0: errors.append('MARKET_CANDLE_REFRESH_SECONDS must be greater than zero')
    if settings.market_candle_max_age_seconds < settings.market_candle_refresh_seconds: errors.append('MARKET_CANDLE_MAX_AGE_SECONDS must not be shorter than MARKET_CANDLE_REFRESH_SECONDS')
    if settings.market_data_future_skew_seconds < 0: errors.append('MARKET_DATA_FUTURE_SKEW_SECONDS cannot be negative')
    if not _valid_provider_url(settings.market_data_rest_base_url, {'https'}): errors.append('MARKET_DATA_REST_BASE_URL must be HTTPS without embedded credentials')
    if not _valid_provider_url(settings.market_data_ws_base_url, {'wss'}): errors.append('MARKET_DATA_WS_BASE_URL must be WSS without embedded credentials')
    if settings.market_data_provider.upper() == 'BINANCE_SPOT':
        if urlparse(settings.market_data_rest_base_url).hostname != 'api.binance.com': errors.append('BINANCE_SPOT REST origin must be api.binance.com')
        if urlparse(settings.market_data_ws_base_url).hostname != 'stream.binance.com': errors.append('BINANCE_SPOT WebSocket origin must be stream.binance.com')
    if not 55 <= settings.market_data_kline_limit <= 1000: errors.append('MARKET_DATA_KLINE_LIMIT must be between 55 and 1000')
    if settings.market_data_rest_max_response_bytes < 16_384: errors.append('MARKET_DATA_REST_MAX_RESPONSE_BYTES is too small')
    if settings.signal_min_recent_trades < 2: errors.append('SIGNAL_MIN_RECENT_TRADES must be at least 2')
    if settings.signal_min_tick_span_seconds <= 0: errors.append('SIGNAL_MIN_TICK_SPAN_SECONDS must be greater than zero')
    if settings.signal_scan_coalesce_ms < 0: errors.append('SIGNAL_SCAN_COALESCE_MS cannot be negative')
    if settings.signal_user_cooldown_seconds <= 0: errors.append('SIGNAL_USER_COOLDOWN_SECONDS must be greater than zero')
    if settings.signal_settlement_window_seconds <= 0: errors.append('SIGNAL_SETTLEMENT_WINDOW_SECONDS must be greater than zero')
    if settings.worker_heartbeat_max_age_seconds <= 0: errors.append('WORKER_HEARTBEAT_MAX_AGE_SECONDS must be greater than zero')
    if settings.temporary_retention_days <= 0: errors.append('TEMPORARY_RETENTION_DAYS must be greater than zero')
    if settings.cleanup_interval_seconds <= 0: errors.append('CLEANUP_INTERVAL_SECONDS must be greater than zero')
    if settings.telegram_webhook_max_body_bytes < 1024: errors.append('TELEGRAM_WEBHOOK_MAX_BODY_BYTES is too small')
    if settings.telegram_update_processing_timeout_seconds <= 0: errors.append('TELEGRAM_UPDATE_PROCESSING_TIMEOUT_SECONDS must be greater than zero')
    if settings.verification_max_deposit_proofs < 1: errors.append('VERIFICATION_MAX_DEPOSIT_PROOFS must be at least 1')
    if settings.verification_max_photo_bytes < 1024: errors.append('VERIFICATION_MAX_PHOTO_BYTES is too small')
    if settings.verification_min_evidence_interval_seconds < 0: errors.append('VERIFICATION_MIN_EVIDENCE_INTERVAL_SECONDS cannot be negative')
    if settings.verification_delivery_max_attempts < 1: errors.append('VERIFICATION_DELIVERY_MAX_ATTEMPTS must be at least 1')

    try:
        countdowns = settings.manual_countdowns()
    except ValueError:
        countdowns = ()
        errors.append('MANUAL_SYNC_ALLOWED_COUNTDOWNS must contain integers')
    if timing_mode == 'MANUAL_SYNC':
        if countdowns != (15, 14, 13, 12): errors.append('V1 manual sync requires countdown buttons 15,14,13,12')
        if settings.manual_sync_min_remaining_after_scan <= 0: errors.append('MANUAL_SYNC_MIN_REMAINING_AFTER_SCAN must be greater than zero')
        if settings.bcgame_round_sync_enabled:
            warnings.append('Automatic round sync is enabled but MANUAL_SYNC remains the active timing mode.')
    if timing_mode == 'AUTO_SYNC' and not settings.bcgame_round_sync_enabled:
        errors.append('AUTO_SYNC requires BCGAME_ROUND_SYNC_ENABLED=true')

    if settings.signals_enabled and mode != 'LIVE': errors.append('SIGNALS_ENABLED=true requires SIGNAL_MODE=LIVE')
    if settings.broadcasts_enabled and not settings.telegram_bot_token: errors.append('BROADCASTS_ENABLED=true requires TELEGRAM_BOT_TOKEN')
    if timing_mode == 'MANUAL_SYNC':
        warnings.append('Manual timing is active: users must tap the button matching BC.GAME at 15/14/13/12 seconds. Start/End timestamps are estimates until AUTO_SYNC is integrated.')

    if settings.app_env.lower() == 'production':
        if settings.database_url.startswith('sqlite'): errors.append('Production must use PostgreSQL, not SQLite')
        if not settings.telegram_bot_token: errors.append('Production requires TELEGRAM_BOT_TOKEN')
        if not settings.telegram_webhook_secret: errors.append('Production requires TELEGRAM_WEBHOOK_SECRET')
        if not settings.owner_telegram_id: errors.append('Production requires OWNER_TELEGRAM_ID')
        if not _valid_https_url(settings.bcgame_registration_url): errors.append('Production requires a valid HTTPS BCGAME_REGISTRATION_URL')
        if not _valid_https_url(settings.bcgame_deposit_url): errors.append('Production requires a valid HTTPS BCGAME_DEPOSIT_URL')
        if not _valid_https_url(settings.bcgame_updown_url): errors.append('Production requires a valid HTTPS BCGAME_UPDOWN_URL')
        elif urlparse(settings.bcgame_updown_url).hostname != 'bc.game' or urlparse(settings.bcgame_updown_url).path.rstrip('/') != '/trading/up-down':
            errors.append('BCGAME_UPDOWN_URL must target https://bc.game/trading/up-down')
        if not _valid_https_url(settings.support_url): errors.append('Production requires a valid HTTPS SUPPORT_URL')
        if len(settings.telegram_webhook_secret or '') < 16: errors.append('TELEGRAM_WEBHOOK_SECRET must be at least 16 characters')

    return StartupCheck(ok=not errors, errors=tuple(errors), warnings=tuple(warnings))
