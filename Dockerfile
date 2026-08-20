FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render provides RENDER_EXTERNAL_URL automatically for web services. Configure
# Telegram's webhook on every web-service start so a fresh deployment cannot be
# live while Telegram is still pointing at an old/missing endpoint. The worker
# overrides this Docker CMD with `python -m app.worker` in render.yaml.
CMD ["sh", "-c", "python scripts/setup_telegram_webhook.py --base-url \"$RENDER_EXTERNAL_URL\" && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
