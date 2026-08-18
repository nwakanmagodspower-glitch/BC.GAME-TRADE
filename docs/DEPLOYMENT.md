# Deployment Plan

## Target

Render is the V1 deployment platform.

## Services

1. **Web Service (Starter)** — Telegram webhook, onboarding/owner verification, on-demand Scan Next Round, health/readiness, lightweight external BTC feed.
2. **Background Worker (Starter)** — independent BTC feed, singleton lifecycle coordination, future BC.GAME round integration, revalidation, notifications, broadcasts, retention cleanup.
3. **PostgreSQL** — persistent product state and worker heartbeat. First PAPER/research month may use Render Free PostgreSQL; upgrade the same database before expiry.
4. **Redis** — deferred.

## Safe First Deployment

The initial deployment is intentionally non-actionable:

```text
SIGNAL_MODE=PAPER
SIGNALS_ENABLED=false
BROADCASTS_ENABLED=false
BCGAME_ROUND_SYNC_ENABLED=false
```

This means the infrastructure/onboarding can be deployed and tested without pretending the old minute-based timing matches BC.GAME.

## Product Environment

```text
GAME_MARKET=BTC/USD
ANALYSIS_PAIR=BTCUSDT
DEFAULT_PAIR=BTCUSDT
DEFAULT_PRODUCT=BC_UPDOWN_5S
DEFAULT_EXPIRY_SECONDS=5
DEFAULT_STAKE_BAND=1-50
STRATEGY_VERSION=BTC_UPDOWN_5S_V1.0
BCGAME_ROUND_SYNC_ENABLED=false
BCGAME_ROUND_SYNC_MAX_AGE_SECONDS=2
SIGNAL_MINIMUM_ACTION_LEAD_SECONDS=5
SIGNAL_SETTLEMENT_WINDOW_SECONDS=2
WORKER_HEARTBEAT_MAX_AGE_SECONDS=30
```

Required secrets/links:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_WEBHOOK_SECRET
OWNER_TELEGRAM_ID
BCGAME_REGISTRATION_URL
BCGAME_DEPOSIT_URL
BCGAME_UPDOWN_URL
SUPPORT_URL
```

Verification packets go directly to the owner's private Telegram conversation with the bot. There is no `ADMIN_CHAT_ID`.

## GitHub Actions Policy

GitHub Actions workflows are disabled at the owner's request because the monthly Actions allowance is unavailable. Do not re-enable or depend on Actions until the owner explicitly changes this instruction.

Validation path:

```text
repository review
→ Render build/pre-deploy migration
→ /health + /ready
→ Telegram smoke tests
→ controlled PAPER round validation
```

## Deployment Gates

### Infrastructure gate

1. Render creates Web + Worker + PostgreSQL.
2. Alembic migrations succeed.
3. Web boots.
4. Worker boots and heartbeat is fresh.
5. `/ready` confirms database connectivity.
6. `/health` shows PAPER, signals off, fresh external BTC data and worker heartbeat.
7. webhook rejects requests without Telegram secret.

### Onboarding gate

1. New user sees registration flow, not main menu.
2. Registration → deposit → User ID → profile proof → deposit proof works.
3. Evidence survives restart.
4. Complete verification packet reaches `OWNER_TELEGRAM_ID` private chat.
5. Approve unlocks menu.
6. Resubmit preserves old reviewed packet and creates new evidence packet.
7. Reject/suspend/block are enforced backend-side.

### Five-second product gate

Before actionable signal mode:

1. Real BC.GAME round synchronization is integrated through `BCGameRoundService`.
2. It identifies a current/upcoming round and actual order-close/first-flag/second-flag timing.
3. Snapshot age passes the configured freshness limit.
4. Human-action lead-time check is measured end-to-end through Telegram.
5. Product is BTC/USD, 5s, approved V1 stake band.
6. Start Rate and End Rate capture is validated against the live interface.
7. Direction decisions are generated from data available before Start Rate.
8. NO_TRADE/UNAVAILABLE behavior is verified.
9. External BTC reference differences from BC.GAME are measured.

Until this gate passes, `BCGAME_ROUND_SYNC_ENABLED` remains false and LIVE mode is prohibited.

## PAPER Validation

PAPER may collect real market/round observations and model decisions, but:

- no `ENTER NOW`;
- no actionable BC.GAME button;
- no claim that external reference result equals BC.GAME result;
- record BC.GAME Start/End Rate whenever trustworthy ingestion is available;
- use unresolved status rather than guessing missing results.

## LIVE Gate

LIVE requires all of the following simultaneously:

- round sync enabled and healthy;
- enough measured PAPER sample;
- strategy version explicitly approved;
- calibrated quality/confidence if shown;
- signal kill switch intentionally enabled;
- latency leaves enough time for manual execution;
- direct BC.GAME link points to the actual Up/Down page;
- no automatic trade placement.

## Database

Keep core history: users, verification packets, strategy decisions, BC.GAME round metadata/results, broadcast summaries, audit state.

Temporary technical records are cleaned after 10 days. Do not store continuous raw tick/order-book streams indefinitely in PostgreSQL.

## Stop Conditions

Stop signal delivery immediately when any of these occurs:

- worker heartbeat stale;
- market feed stale;
- round sync stale/missing;
- order window too close to closing;
- round/product/duration mismatch;
- unexpected strategy version;
- duplicate lifecycle processing;
- BC.GAME Start/End Rate cannot be trusted;
- PAPER presentation becomes actionable;
- kill switch is off.
