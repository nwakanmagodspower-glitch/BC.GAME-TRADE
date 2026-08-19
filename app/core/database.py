from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

settings = get_settings()


def normalize_database_url(url: str) -> str:
    """Use the installed psycopg 3 driver for generic Render/Postgres URLs."""
    if url.startswith('postgres://'):
        return 'postgresql+psycopg://' + url[len('postgres://'):]
    if url.startswith('postgresql://'):
        return 'postgresql+psycopg://' + url[len('postgresql://'):]
    return url


database_url = normalize_database_url(settings.database_url)
connect_args = {'check_same_thread': False} if database_url.startswith('sqlite') else {}
engine_options = {'pool_pre_ping': True, 'connect_args': connect_args}
if not database_url.startswith('sqlite'):
    engine_options.update(pool_size=5, max_overflow=10, pool_timeout=10, pool_recycle=300)
engine = create_engine(database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
