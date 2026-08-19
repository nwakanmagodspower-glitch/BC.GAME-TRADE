# Render Deployment Checklist

## Blueprint

The repository defines:

1. `bcgame-trade-api` — Starter web, Frankfurt.
2. `bcgame-trade-worker` — Starter worker, Frankfurt.
3. `bcgame-trade-db` — PostgreSQL 16, Free for PAPER validation only.

Render Free PostgreSQL expires after 30 days and has no backups. Upgrade the same database to at least `basic-256mb` before admitting controlled-beta users. Redis is not required for 10–250-user testing.

## Safe checked-in state

```text
SIGNAL_MODE=PAPER
SIGNALS_ENABLED=false
BROADCASTS_ENABLED=false
SIGNAL_TIMING_MODE=MANUAL_SYNC
MANUAL_SYNC_ALLOWED_COUNTDOWNS=15,14,13,12
MANUAL_SYNC_MIN_REMAINING_AFTER_SCAN=7
BCGAME_ROUND_SYNC_ENABLED=false
```

Product identity:

```text
GAME_MARKET=BTC/USD
ANALYSIS_PAIR=BTCUSDT
DEFAULT_PRODUCT=BC_UPDOWN_5S
DEFAULT_EXPIRY_SECONDS=5
DEFAULT_STAKE_BAND=1-50
STRATEGY_VERSION=BTC_UPDOWN_5S_V1.1
```

Required secret/link values:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET` (at least 16 characters)
- `OWNER_TELEGRAM_ID` (private verification inbox)
- `BCGAME_REGISTRATION_URL`
- `BCGAME_DEPOSIT_URL`
- `BCGAME_UPDOWN_URL=https://bc.game/trading/up-down`
- `SUPPORT_URL`

There is no `ADMIN_CHAT_ID`. The owner must start the bot once before receiving packets.

## First boot

1. Render pre-deploy runs `alembic upgrade head` and reaches `0007_security_delivery_hardening`.
2. Web and worker start.
3. `/ready` returns 200.
4. `/health` reports PAPER, signals/broadcasts off, correct product identity, fresh BTCUSDT reference data, fresh candle context and worker heartbeat.
5. `/market/status` labels BTCUSDT external-reference-only.
6. Unauthenticated, non-JSON and oversized webhook requests are rejected.
7. Run `python scripts/render_smoke_test.py --base-url https://<service>.onrender.com`.

## Telegram onboarding

- New users receive the guided funnel, not the main menu.
- Evidence count/size/rate limits reject excess screenshots.
- Submission creates a durable owner-delivery record.
- The worker sends all evidence before owner decision buttons.
- Approve unlocks the menu; reject and resubmit work; resubmission preserves the old packet.
- Suspension/blocking is enforced on request and async delivery paths.

## Controlled beta promotion

After the safe deployment and owner approval, set on both services:

```text
SIGNAL_MODE=LIVE
SIGNALS_ENABLED=true
BROADCASTS_ENABLED=true
```

Do not enable `AUTO_SYNC`. Validate the 15/14/13/12 buttons, seven-second post-scan floor, NO_TRADE/UNAVAILABLE distinction, correct game link, current-signal serialization, scan cooldown and external-reference labels. Re-run the smoke script with `--expect-mode LIVE`.

## GitHub Actions

Do not create, enable or depend on GitHub Actions while the owner's allowance is exhausted. Use local tests, Render pre-deploy migration, health/readiness and Telegram smoke tests.

## Scale triggers

- 10 users: current services are ample.
- 100 users: comfortable if synchronized signal bursts are monitored.
- 250 users: reasonable test target; watch PostgreSQL connections, webhook latency and Telegram rate limits.
- 1,000 users: not proven. Load-test first; likely add horizontal web capacity, shared cache/queueing and delivery controls.
