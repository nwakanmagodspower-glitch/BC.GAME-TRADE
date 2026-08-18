from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import Settings
from app.core.startup import StartupCheck, validate_settings


@dataclass(frozen=True)
class SystemStatus:
    startup: StartupCheck
    database_ok: bool

    @property
    def ready(self) -> bool:
        return self.startup.ok and self.database_ok


class SystemService:
    def __init__(self, settings: Settings, engine: Engine):
        self.settings = settings
        self.engine = engine

    def check(self) -> SystemStatus:
        startup = validate_settings(self.settings)
        database_ok = False
        if startup.ok:
            try:
                with self.engine.connect() as connection:
                    connection.execute(text('SELECT 1'))
                database_ok = True
            except Exception:
                database_ok = False
        return SystemStatus(startup=startup, database_ok=database_ok)
