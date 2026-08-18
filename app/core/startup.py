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
    return parsed.scheme == 'https' and bool(parsed.netloc)


def validate_settings(settings: Settings) -> StartupCheck:
    errors: list[str] = []
    warnings: list[str] = []
    mode = settings.signal_mode.upper()

    if mode not in {'PAPER', 'LIVE'}:
        errors.append('SIGNAL_MODE must be PAPER or LIVE')
    if settings.game_market.upper() != 'BTC/USD':
        errors.append('V1 requires GAME_MARKET=BTC/USD')
    if settings.analysis_pair.upper() != 'BTCUSDT' or settings.default_pair.upper() != 'BTCUSDT':
        errors.append('V1 analysis feed requires BTCUSDT')
    if settings.default_product.upper() != 'BC_UPDOWN_5S':
        errors.append('V1 requires DEFAULT_PRODUCT=BC_UPDOWN_5S')
    if settings.default_expiry_seconds != 5:
        errors.append('V1 requires DEFAULT_EXPIRY_SECONDS=5')
    if settings.default_stake_band != '1-50':
        errors.append('V1 requires DEFAULT_STAKE_BAND=1-50')
    if not settings.strategy_version.startswith('BTC_UPDOWN_5S_V1'):
        errors.append('V1 strategy identity must remain BTC_UPDOWN_5S_V1.x')
    if settings.market_data_max_age_seconds <= 0:
        errors.append('MARKET_DATA_MAX_AGE_SECONDS must be greater than zero')
    if settings.bcgame_round_sync_max_age_seconds <= 0:
        errors.append('BCGAME_ROUND_SYNC_MAX_AGE_SECONDS must be greater than zero')
    if settings.signal_minimum_action_lead_seconds <= 0:
        errors.append('SIGNAL_MINIMUM_ACTION_LEAD_SECONDS must be greater than zero')
    if settings.signal_settlement_window_seconds <= 0:
        errors.append('SIGNAL_SETTLEMENT_WINDOW_SECONDS must be greater than zero')
    if settings.worker_heartbeat_max_age_seconds <= 0:
        errors.append('WORKER_HEARTBEAT_MAX_AGE_SECONDS must be greater than zero')
    if settings.temporary_retention_days <= 0:
        errors.append('TEMPORARY_RETENTION_DAYS must be greater than zero')
    if settings.cleanup_interval_seconds <= 0:
        errors.append('CLEANUP_INTERVAL_SECONDS must be greater than zero')

    if settings.signals_enabled and mode != 'LIVE':
        errors.append('SIGNALS_ENABLED=true requires SIGNAL_MODE=LIVE')
    if mode == 'LIVE' and not settings.bcgame_round_sync_enabled:
        errors.append('LIVE mode requires BCGAME_ROUND_SYNC_ENABLED=true')
    if settings.broadcasts_enabled and not settings.telegram_bot_token:
        errors.append('BROADCASTS_ENABLED=true requires TELEGRAM_BOT_TOKEN')

    if not settings.bcgame_round_sync_enabled:
        warnings.append('BC.GAME round synchronization is not connected; actionable round-timed signals must remain disabled.')

    if settings.app_env.lower() == 'production':
        if settings.database_url.startswith('sqlite'):
            errors.append('Production must use PostgreSQL, not SQLite')
        if not settings.telegram_bot_token:
            errors.append('Production requires TELEGRAM_BOT_TOKEN')
        if not settings.telegram_webhook_secret:
            errors.append('Production requires TELEGRAM_WEBHOOK_SECRET')
        if not settings.owner_telegram_id:
            errors.append('Production requires OWNER_TELEGRAM_ID')
        if not _valid_https_url(settings.bcgame_registration_url):
            errors.append('Production requires a valid HTTPS BCGAME_REGISTRATION_URL')
        if not _valid_https_url(settings.bcgame_deposit_url):
            errors.append('Production requires a valid HTTPS BCGAME_DEPOSIT_URL')
        if not _valid_https_url(settings.bcgame_updown_url):
            errors.append('Production requires a valid HTTPS BCGAME_UPDOWN_URL')
        if not _valid_https_url(settings.support_url):
            errors.append('Production requires a valid HTTPS SUPPORT_URL')
        if len(settings.telegram_webhook_secret or '') < 16:
            errors.append('TELEGRAM_WEBHOOK_SECRET must be at least 16 characters')

    return StartupCheck(ok=not errors, errors=tuple(errors), warnings=tuple(warnings))
