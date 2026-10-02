"""Pre-deploy database readiness probe and Alembic migration runner.

Guards against 'Connection refused' during initial database provisioning
when a new Render PostgreSQL instance is still booting up.
"""

from __future__ import annotations

import logging
import sys
import time

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.database import normalize_database_url

logger = logging.getLogger(__name__)


def wait_for_database(max_retries: int = 30, retry_interval_seconds: float = 2.0) -> None:
    settings = get_settings()
    url = normalize_database_url(settings.database_url)
    engine = create_engine(url)

    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"✓ Database reachable and accepting connections (attempt {attempt}/{max_retries}).")
            return
        except Exception as exc:
            print(
                f"[Attempt {attempt}/{max_retries}] Database not ready yet: {exc}. Retrying in {retry_interval_seconds}s..."
            )
            if attempt == max_retries:
                print("❌ Timed out waiting for database connection.")
                raise
            time.sleep(retry_interval_seconds)


def run_migrations() -> None:
    print("Running Alembic upgrade head...")
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    print("✓ Alembic migrations successfully applied.")


def main() -> None:
    wait_for_database()
    run_migrations()


if __name__ == "__main__":
    main()
