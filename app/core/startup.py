from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.config import Settings


@dataclass(frozen=True)
class StartupCheck:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _valid_https_url(value: str | None) -> bool:
    if not value: return False
    parsed = urlparse(value)
    return parsed.scheme == 'https' and bool(parsed.netloc)


def validate_settings(settings: Settings) -> StartupCheck:
    errors: list[str] = []
    warnings: list[str] = []
    mode = settings.signal_mode.upper()

    if mode not in {'PAPER', 'LIVE'}: errors.append('SIGNAL_MODE must be PAPER or LIVE')
    if settings.default_pair.upper() != 'BTCUSDT': errors.append('V1 requires DEFAULT_PAIR=BTCUSDT')
    if settings.default_product.upper() != 'BC_UPDOWN': errors.append('V1 requires DEFAULT_PRODUCT=BC_UPDOWN')
    if settings.default_expiry_seconds != 300: errors.append('V1 requires DEFAULT_EXPIRY_SECONDS=300')
    if not settings.strategy_version.startswith('BTC_UPDOWN_V1'): errors.append('V1 strategy identity must remain BTC_UPDOWN_V1.x')
    if settings.market_data_max_age_seconds <= 0: errors.append('MARKET_DATA_MAX_AGE_SECONDS must be greater than zero')

    if settings.signals_enabled and mode != 'LIVE':
        errors.append('SIGNALS_ENABLED=true requires SIGNAL_MODE=LIVE')
    if settings.broadcasts_enabled and not settings.telegram_bot_token:
        errors.append('BROADCASTS_ENABLED=true requires TELEGRAM_BOT_TOKEN')

    if settings.app_env.lower() == 'production':
        if settings.database_url.startswith('sqlite'): errors.append('Production must use PostgreSQL, not SQLite')
        if not settings.telegram_bot_token: errors.append('Production requires TELEGRAM_BOT_TOKEN')
        if not settings.telegram_webhook_secret: errors.append('Production requires TELEGRAM_WEBHOOK_SECRET')
        if not settings.owner_telegram_id: errors.append('Production requires OWNER_TELEGRAM_ID')
        if not _valid_https_url(settings.bcgame_registration_url): errors.append('Production requires a valid HTTPS BCGAME_REGISTRATION_URL')
        if not _valid_https_url(settings.bcgame_deposit_url): errors.append('Production requires a valid HTTPS BCGAME_DEPOSIT_URL')
        if not _valid_https_url(settings.bcgame_updown_url): errors.append('Production requires a valid HTTPS BCGAME_UPDOWN_URL')
        if not _valid_https_url(settings.support_url): errors.append('Production requires a valid HTTPS SUPPORT_URL')
        if len(settings.telegram_webhook_secret or '') < 16: errors.append('TELEGRAM_WEBHOOK_SECRET must be at least 16 characters')

    return StartupCheck(ok=not errors, errors=tuple(errors), warnings=tuple(warnings))
