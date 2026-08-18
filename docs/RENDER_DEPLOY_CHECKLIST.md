# Render Deployment Checklist

This checklist is subordinate to `AGENTS.md`, `ARCHITECTURE.md`, `DEPLOYMENT.md`, `STRATEGY_RULES.md`, and `MILESTONES.md`.

## Before creating Render resources

- Confirm `main` contains the intended release.
- Confirm migrations are present for every schema change.
- Confirm `SIGNAL_MODE=PAPER`.
- Confirm `SIGNALS_ENABLED=false`.
- Confirm `BROADCASTS_ENABLED=false`.
- Confirm V1 identity remains `BTCUSDT` + `BC_UPDOWN` + 300-second expiry.
- Prepare secrets outside GitHub.

## Render Blueprint

Create from `render.yaml`. Expected resources:

1. `bcgame-trade-api` web service.
2. `bcgame-trade-worker` background worker.
3. `bcgame-trade-db` PostgreSQL.

The web service runs migrations using `alembic upgrade head` as the pre-deploy command.

## Required production values

Set all secret `sync: false` variables in Render:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET` (minimum 16 characters)
- `OWNER_TELEGRAM_ID`
- `ADMIN_CHAT_ID`
- `BCGAME_REGISTRATION_URL`
- `BCGAME_DEPOSIT_URL`
- `BCGAME_UPDOWN_URL`
- `SUPPORT_URL`

Do not enable signals or broadcasts during first deployment.

## First boot verification

1. Web deployment succeeds.
2. Worker deployment succeeds without configuration error.
3. Pre-deploy migration succeeds.
4. `/health` returns HTTP 200.
5. `/ready` returns HTTP 200.
6. `/market/status` reports fresh BTCUSDT data.
7. An unauthenticated POST to `/telegram/webhook` is rejected.
8. Run:

```bash
python scripts/render_smoke_test.py --base-url https://YOUR-SERVICE.onrender.com
```

The smoke test must pass before webhook registration.

## Telegram webhook registration

After the web service is healthy, run from an environment containing the same production variables:

```bash
python scripts/setup_telegram_webhook.py --base-url https://YOUR-SERVICE.onrender.com
```

Then verify `/start` reaches the bot and onboarding remains gated.

## Functional smoke checks

With signals and broadcasts still disabled:

- new user sees registration step, not main menu;
- registration/deposit/profile/deposit-proof flow resumes after interruption;
- verification packet reaches admin;
- admin approve unlocks main menu;
- non-owner cannot use `/admin` controls;
- owner `/admin` reports PAPER and signals OFF;
- BTC Signal action refuses because signals are disabled;
- broadcast can be drafted/previewed but cannot queue while `BROADCASTS_ENABLED=false`;
- support link opens configured support destination.

## Paper-validation transition

Do not change to LIVE for M11. Keep `SIGNAL_MODE=PAPER`.

When M11 is intentionally started, enable only the runtime signal gate needed for controlled paper testing according to the documented test procedure. Automated BC.GAME trade placement remains prohibited.

## Stop conditions

Stop deployment validation and repair before proceeding if any of these occur:

- database migration error;
- stale/unavailable market data;
- webhook secret failure;
- duplicate worker processing;
- onboarding bypass;
- unauthorized admin access;
- signal delivery while a required kill switch is off;
- broadcast delivery while `BROADCASTS_ENABLED=false`;
- unexpected strategy version/pair/product/expiry.
