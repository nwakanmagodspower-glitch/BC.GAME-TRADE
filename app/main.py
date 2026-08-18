from fastapi import FastAPI
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine

settings = get_settings()
app = FastAPI(title=settings.app_name)


@app.get('/health')
def health():
    return {
        'status': 'ok',
        'app': settings.app_name,
        'env': settings.app_env,
        'signal_mode': settings.signal_mode,
        'signals_enabled': settings.signals_enabled,
    }


@app.get('/ready')
def ready():
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
    return {'status': 'ready'}
