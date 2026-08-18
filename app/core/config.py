from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'BC.GAME TRADE'
    app_env: str = 'development'
    database_url: str = 'sqlite:///./bcgame_trade.db'

    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    owner_telegram_id: int | None = None

    signal_mode: str = 'PAPER'
    signals_enabled: bool = False
    default_pair: str = 'BTCUSDT'
    default_expiry_seconds: int = 300
    strategy_version: str = 'BTC_UPDOWN_V1.0'

    market_data_max_age_seconds: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
