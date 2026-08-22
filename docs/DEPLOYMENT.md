# Deployment

## Existing Render resources

The Blueprint intentionally preserves:

- web: `bcgame-trade-api`
- worker: `bcgame-trade-worker`
- database: `bcgame-trade-db`
- branch: `main`
- automatic deploy on commit
- `alembic upgrade head` before the web deployment

Do not create duplicate services. The web owns Telegram webhook handling and the shared DeTrade observer. The worker owns singleton background delivery/lifecycle/cleanup jobs. Both use independent Binance streams and the same PostgreSQL database.

## Private values

These remain private and user-supplied in Render:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET`
- `OWNER_TELEGRAM_ID`
- `DETRADE_WS_TOKEN` (ephemeral and optional for HYBRID fallback)
- registration, deposit, Up/Down, and support URLs
- the database connection, supplied by Render

Never paste a token into `render.yaml`, source, GitHub, issue text, logs, Telegram, or documentation. A token replacement causes a web-service restart; this is required because a rejected environment token is never reused in-process.

## HYBRID behavior

Production uses `SIGNAL_TIMING_MODE=HYBRID_SYNC`, round sync enabled, and the DeTrade observer enabled. If the secret is absent, a known placeholder, expired, or rejected, startup remains healthy and Scan Now uses manual fallback. If a fresh authoritative frame says the round is unsafe, the request is rejected rather than falling back.

Use `AUTO_SYNC` only when a valid token is present and operations explicitly prefer complete outage over fallback. Startup rejects AUTO without the observer and usable authorization.

## Commands

The Docker web command configures the Telegram webhook against Render’s external URL, then starts Uvicorn without reload/debug mode. The worker command remains:

```text
python -m app.worker
```

Useful smoke checks:

```bash
python -m scripts.render_smoke_test --base-url https://<existing-service-host>
python -m scripts.paper_validation_report
```

The owner-only `/round_status` command is the credential-safe synchronized-timer probe.

## Rollback

This change has no database migration. Rollback can use Render’s previous image/commit. Do not downgrade the database merely to roll back application code. If authorization behaves unexpectedly, remove/rotate only `DETRADE_WS_TOKEN`; HYBRID will fall back without disabling onboarding/support.
