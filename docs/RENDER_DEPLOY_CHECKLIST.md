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

## Render Blueprint — first month

Create from root `render.yaml`. Expected resources:

1. `bcgame-trade-api` — Starter web service, Frankfurt.
2. `bcgame-trade-worker` — Starter background worker, Frankfurt.
3. `bcgame-trade-db` — Free PostgreSQL 16, Frankfurt.

Expected first-month base service cost is the two paid Starter services; the database uses Render's Free Postgres tier for the initial PAPER-validation month.

The web service has `RUN_BACKGROUND_JOBS=false`. It handles Telegram webhooks, onboarding/admin requests, on-demand BTC scans, health/readiness endpoints, and its own lightweight BTC market feed.

The worker runs `python -m app.worker`. It maintains its own lightweight BTC market feed and owns signal lifecycle, entry/expiry settlement, lifecycle notifications, broadcast delivery, and 10-day retention cleanup.

The worker uses the PostgreSQL advisory-lock coordinator before starting singleton jobs. This protects against duplicate processing when Render briefly overlaps old and new worker instances during a zero-downtime deployment.

The web service runs `alembic upgrade head` as its pre-deploy command. PostgreSQL external access is disabled with `ipAllowList: []`; web and worker use the same-region internal database connection.

## Free PostgreSQL first-month limits

Render Free Postgres is for the initial testing/PAPER period only:

- fixed 1 GB storage;
- expires 30 days after creation;
- no managed backups;
- no managed connection pooling;
- Render may restart it for maintenance;
- after expiry there is a 14-day grace period to upgrade before deletion.

Do **not** plan to wait until expiry. Target upgrade around day 25–28 to a paid Postgres plan. Confirm the upgrade is complete and the database remains accessible before day 30.

## Required production values

During initial Blueprint creation, provide these `sync: false` values on `bcgame-trade-api`:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET` (minimum 16 characters)
- `OWNER_TELEGRAM_ID`
- `BCGAME_REGISTRATION_URL`
- `BCGAME_DEPOSIT_URL`
- `BCGAME_UPDOWN_URL`
- `SUPPORT_URL`

`OWNER_TELEGRAM_ID` is both the owner authorization identity and the private Telegram chat destination for verification packets. No separate admin group/chat is required. The owner must have opened/started the bot at least once so Telegram allows the bot to message that private chat.

The worker inherits these values from the web service with Render `fromService` references. Do not create separate conflicting copies.

Do not enable signals or broadcasts during first deployment.

## First boot verification

1. Free PostgreSQL is created successfully.
2. Web pre-deploy migration succeeds against PostgreSQL.
3. `bcgame-trade-api` deployment succeeds.
4. `bcgame-trade-worker` deployment succeeds.
5. `/health` returns HTTP 200 and reports `topology=web-plus-dedicated-worker`.
6. `/health` reports a fresh dedicated-worker heartbeat (normally <=30 seconds old).
7. `/ready` returns HTTP 200.
8. `/market/status` reports fresh BTCUSDT data.
9. An unauthenticated POST to `/telegram/webhook` is rejected.
10. Run:

```bash
python scripts/render_smoke_test.py --base-url https://YOUR-SERVICE.onrender.com
```

The smoke test must pass before webhook registration.

If the worker heartbeat is missing immediately after first boot, wait briefly and recheck while viewing worker logs. It must become fresh before proceeding.

## Telegram webhook registration

After the web service and worker are healthy, run from an environment containing the same production variables:

```bash
python scripts/setup_telegram_webhook.py --base-url https://YOUR-SERVICE.onrender.com
```

Then verify `/start` reaches the bot and onboarding remains gated.

## Functional smoke checks

With signals and broadcasts still disabled:

- owner has started the bot once so the bot can message the owner's private chat;
- new user sees registration step, not main menu;
- registration/deposit/profile/deposit-proof flow resumes after interruption;
- verification packet reaches the owner's private bot chat;
- packet contains BC.GAME User ID, profile proof, deposit proof(s), and Approve / Resubmit / Reject controls;
- resubmission preserves the reviewed packet and creates a new evidence packet;
- owner approval unlocks main menu;
- non-owner cannot use `/admin` or verification-review controls;
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

When M11 is intentionally started, enable only the runtime signal gate required for controlled paper testing according to the documented test procedure. PAPER messages must remain explicitly non-actionable: no `ENTER NOW` language and no BC.GAME execution button.

Automated BC.GAME trade placement remains prohibited.

## Database upgrade before expiry

Around day 25–28:

1. Open `bcgame-trade-db` in Render.
2. Upgrade the same database from Free to the chosen paid Postgres instance type.
3. Confirm the database becomes Available.
4. Confirm `bcgame-trade-api` `/ready` remains HTTP 200.
5. Confirm `/health` still shows a fresh worker heartbeat.
6. Confirm users, approvals, verification history, and paper signal history remain intact.
7. Repeat `scripts/render_smoke_test.py`.

Do not create a second production database unless a migration plan explicitly requires it.

## Stop conditions

Stop deployment validation and repair before proceeding if any of these occur:

- database migration error;
- stale/unavailable market data recorded as strategy `NO_TRADE`;
- webhook secret failure;
- dedicated worker heartbeat stale/missing after startup settles;
- duplicate lifecycle/broadcast processing despite worker leader coordination;
- onboarding bypass;
- verification packet goes to any destination other than the configured owner's private bot chat;
- resubmission overwrites old verification evidence;
- unauthorized admin access;
- PAPER mode shows a BC.GAME execution button or `ENTER NOW` instruction;
- signal delivery while a required kill switch is off;
- broadcast delivery while `BROADCASTS_ENABLED=false`;
- unexpected strategy version/pair/product/expiry.
