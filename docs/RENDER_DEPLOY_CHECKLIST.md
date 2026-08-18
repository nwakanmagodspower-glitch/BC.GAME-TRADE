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

## Render Blueprint — 0 to 250 users

Create from root `render.yaml`. Expected paid resources:

1. `bcgame-trade-api` Starter web service — Frankfurt.
2. `bcgame-trade-db` PostgreSQL 16 Basic-256MB — Frankfurt, 1 GB disk.

There is no separate paid background worker in this stage. `RUN_BACKGROUND_JOBS=true` makes the web process host the already-separated signal lifecycle worker, broadcast worker, and 10-day retention cleanup task.

The web service runs migrations using `alembic upgrade head` as the pre-deploy command. PostgreSQL external access is disabled (`ipAllowList: []`).

### Combined-topology coordination and scaling rule

Render zero-downtime deploys temporarily overlap the old and new web instances. The combined topology therefore uses a PostgreSQL advisory leader lock: only the lock holder may run signal lifecycle, broadcast delivery, and retention cleanup. A replacement instance keeps retrying and takes leadership after the previous instance shuts down.

For the 0–250-user cost plan, keep one steady-state web instance. The leader lock protects correctness during deploy/maintenance overlap, but running multiple permanent web instances would unnecessarily duplicate market-feed/API compute and increase cost.

When sustained concurrency justifies horizontal web scaling, switch to the existing dedicated `app.worker` topology: set `RUN_BACKGROUND_JOBS=false` on web and provision one separate background worker. This requires configuration change, not a rewrite of business logic.

## Required production values

During initial Blueprint creation, provide these `sync: false` values:

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
2. Pre-deploy migration succeeds against PostgreSQL.
3. `/health` returns HTTP 200 and reports `topology=combined`.
4. `/health` reports background jobs enabled with no coordinator/worker/cleanup errors.
5. In steady state, `/health` reports `background_jobs.leader=true` on the single running web instance.
6. `/ready` returns HTTP 200.
7. `/market/status` reports fresh BTCUSDT data.
8. An unauthenticated POST to `/telegram/webhook` is rejected.
9. Run:

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
- resubmission preserves the reviewed packet and creates a new evidence packet;
- admin approve unlocks main menu;
- non-owner cannot use `/admin` controls;
- owner `/admin` reports PAPER and signals OFF;
- BTC Signal opens context first and requires explicit `Scan Now`;
- BTC Signal action refuses because signals are disabled;
- broadcast can be drafted/previewed but cannot queue while `BROADCASTS_ENABLED=false`;
- support link opens configured support destination.

## Retention verification

- `TEMPORARY_RETENTION_DAYS=10`.
- `CLEANUP_INTERVAL_SECONDS=86400`.
- temporary webhook receipts, signal-notification delivery records, and completed broadcast-delivery rows older than 10 days are removable;
- terminal signals older than the retention window are not re-notified merely because their old delivery receipt was cleaned;
- users, verification history, signals/results, broadcast summaries, runtime settings, and audit history are not part of temporary cleanup.

## Paper-validation transition

Do not change to LIVE for M11. Keep `SIGNAL_MODE=PAPER`.

When M11 is intentionally started, enable only the runtime signal gate needed for controlled paper testing according to the documented test procedure. PAPER messages must remain explicitly non-actionable: no `ENTER NOW` language and no BC.GAME execution button.

Automated BC.GAME trade placement remains prohibited.

## Stop conditions

Stop deployment validation and repair before proceeding if any of these occur:

- database migration error;
- stale/unavailable market data recorded as strategy `NO_TRADE`;
- webhook secret failure;
- no background-job leader in steady state;
- duplicate lifecycle/broadcast processing despite leader coordination;
- onboarding bypass;
- resubmission overwrites old verification evidence;
- unauthorized admin access;
- PAPER mode shows a BC.GAME execution button or `ENTER NOW` instruction;
- signal delivery while a required kill switch is off;
- broadcast delivery while `BROADCASTS_ENABLED=false`;
- unexpected strategy version/pair/product/expiry.
