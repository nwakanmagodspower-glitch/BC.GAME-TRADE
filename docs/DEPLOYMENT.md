# Deployment Plan

## Deployment Target

Render is the production platform for V1.

## Services

1. **Web Service** — Telegram webhook, onboarding/admin application requests, on-demand scans, health/readiness endpoints, lightweight BTC feed.
2. **Background Worker** — its own lightweight BTC feed, timed entry revalidation, settlement, lifecycle notifications, broadcasts, retention cleanup.
3. **PostgreSQL** — persistent application state and worker heartbeat.
4. **Optional Redis** — deferred until scaling evidence justifies it.

For the first PAPER-validation month, the Blueprint uses paid Starter web + paid Starter worker + Render Free PostgreSQL. Upgrade the same database before its free-period expiry.

## Required Environment Variables

```text
APP_ENV=production
DATABASE_URL=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
OWNER_TELEGRAM_ID=...
SIGNAL_MODE=PAPER
SIGNALS_ENABLED=false
BROADCASTS_ENABLED=false
DEFAULT_PAIR=BTCUSDT
DEFAULT_PRODUCT=BC_UPDOWN
DEFAULT_EXPIRY_SECONDS=300
STRATEGY_VERSION=BTC_UPDOWN_V1.0
SIGNAL_SETTLEMENT_WINDOW_SECONDS=3
WORKER_HEARTBEAT_MAX_AGE_SECONDS=30
BCGAME_REGISTRATION_URL=...
BCGAME_DEPOSIT_URL=...
BCGAME_UPDOWN_URL=...
SUPPORT_URL=...
```

Secrets must live in Render, never GitHub. Verification packets are delivered directly to `OWNER_TELEGRAM_ID`; V1 does not require a separate admin group/chat ID.

## Required Endpoints

- `/health` — process alive, market feed status, dedicated-worker heartbeat.
- `/ready` — configuration + database readiness.
- `/telegram/webhook` — secret-protected Telegram webhook.

## Deployment Gates

A release may progress only when all earlier gates pass:

1. App boots locally.
2. Configuration validation passes.
3. Database migrations apply cleanly.
4. Health/readiness endpoints pass.
5. Dedicated-worker heartbeat becomes fresh.
6. Telegram webhook verifies correctly.
7. Guided onboarding works end to end.
8. Verification packet reaches the owner private bot chat correctly.
9. Owner decision persists and unlocks/blocks access correctly.
10. BTC market feeds pass freshness checks.
11. Signal engine returns structured `UP/DOWN/NO_TRADE/UNAVAILABLE` decisions.
12. Signal requests fail closed when the dedicated worker is unhealthy.
13. Exact entry timing and pre-entry revalidation work in paper mode.
14. Outcome settlement uses only the bounded expiry-reference window and marks unreliable settlement unresolved.
15. Broadcast queue works without blocking signal requests.
16. Render deploy passes smoke tests.
17. Controlled paper-production run passes before live user signals.

## Production Modes

### `PAPER`

Real market data, real signal generation, outcomes tracked, but not presented as actionable trade recommendations. No `ENTER NOW` execution prompt or BC.GAME trading button.

### `LIVE`

Signals may be presented to approved users for manual execution. This still does **not** mean automated trade placement.

## Kill Switches

At minimum:

```text
SIGNALS_ENABLED=false
BROADCASTS_ENABLED=false
```

The owner must be able to disable signal delivery independently of Telegram onboarding and support.

## Deployment Safety

- Never deploy schema changes without migrations.
- Never expose a webhook without secret validation.
- Never mark service ready if database is unavailable.
- Never create a production waiting signal if the dedicated worker heartbeat is stale.
- Never issue signals if market data freshness fails.
- Never activate a candidate before planned entry time.
- Never settle WIN/LOSS/TIE using a materially late expiry reference.
- Never activate live mode as part of an unrelated deployment.
- Roll forward with a new strategy version; do not mutate historical strategy identity.
