from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class StartupCheck:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_settings(settings: Settings) -> StartupCheck:
    errors: list[str] = []
    warnings: list[str] = []

    allowed_modes = {'PAPER', 'LIVE'}
    if settings.signal_mode.upper() not in allowed_modes:
        errors.append(f'SIGNAL_MODE must be one of {sorted(allowed_modes)}')

    if settings.default_pair.upper() != 'BTCUSDT':
        warnings.append('V1 scope is BTCUSDT only; DEFAULT_PAIR differs from BTCUSDT')

    if settings.default_expiry_seconds <= 0:
        errors.append('DEFAULT_EXPIRY_SECONDS must be greater than zero')

    if settings.market_data_max_age_seconds <= 0:
        errors.append('MARKET_DATA_MAX_AGE_SECONDS must be greater than zero')

    if settings.app_env.lower() == 'production':
        if settings.database_url.startswith('sqlite'):
            errors.append('Production must use PostgreSQL, not SQLite')
        if not settings.telegram_bot_token:
            warnings.append('TELEGRAM_BOT_TOKEN is not configured yet; Telegram remains inactive')
        if not settings.telegram_webhook_secret:
            warnings.append('TELEGRAM_WEBHOOK_SECRET is not configured yet')

    if settings.signals_enabled and settings.signal_mode.upper() != 'LIVE':
        warnings.append('Signals are enabled while SIGNAL_MODE is not LIVE')

    return StartupCheck(ok=not errors, errors=tuple(errors), warnings=tuple(warnings))
