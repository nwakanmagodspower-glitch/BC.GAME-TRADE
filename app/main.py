from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.core.startup import validate_settings

settings = get_settings()
startup_check = validate_settings(settings)

app = FastAPI(title=settings.app_name)


@app.get('/health')
def health():
    return {
        'status': 'ok',
        'app': settings.app_name,
        'env': settings.app_env,
        'signal_mode': settings.signal_mode,
        'signals_enabled': settings.signals_enabled,
        'startup_ok': startup_check.ok,
        'startup_warnings': startup_check.warnings,
    }


@app.get('/ready')
def ready():
    if not startup_check.ok:
        raise HTTPException(status_code=503, detail={'errors': startup_check.errors})

    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
    except Exception as exc:
        raise HTTPException(status_code=503, detail='database_unavailable') from exc

    return {'status': 'ready'}
