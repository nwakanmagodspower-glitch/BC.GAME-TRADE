# Render Deployment Checklist

## Before Creating Resources

- main contains intended release;
- migration chain includes `0006_bcgame_rounds`;
- `SIGNAL_MODE=PAPER`;
- `SIGNALS_ENABLED=false`;
- `BROADCASTS_ENABLED=false`;
- `BCGAME_ROUND_SYNC_ENABLED=false` until a real structured provider is integrated;
- V1 identity: `BTC/USD` game market + `BTCUSDT` analysis + `BC_UPDOWN_5S` + 5 seconds + `$1-50`;
- no GitHub Actions dependency.

## Blueprint — First Month

Expected:

1. `bcgame-trade-api` — Starter web, Frankfurt.
2. `bcgame-trade-worker` — Starter worker, Frankfurt.
3. `bcgame-trade-db` — Free PostgreSQL 16 initially.

First-month base compute: the two paid Starter services. Upgrade the same Free PostgreSQL before expiry once history is valuable.

## Required Values

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET` (>=16 chars)
- `OWNER_TELEGRAM_ID`
- `BCGAME_REGISTRATION_URL`
- `BCGAME_DEPOSIT_URL`
- `BCGAME_UPDOWN_URL` — target `https://bc.game/trading/up-down`
- `SUPPORT_URL`

`OWNER_TELEGRAM_ID` is the private verification inbox. No separate `ADMIN_CHAT_ID`. Owner must start the bot once before the bot can deliver private verification packets.

## Product Defaults

Confirm Render shows:

```text
GAME_MARKET=BTC/USD
ANALYSIS_PAIR=BTCUSDT
DEFAULT_PRODUCT=BC_UPDOWN_5S
DEFAULT_EXPIRY_SECONDS=5
DEFAULT_STAKE_BAND=1-50
STRATEGY_VERSION=BTC_UPDOWN_5S_V1.0
BCGAME_ROUND_SYNC_ENABLED=false
SIGNAL_MINIMUM_ACTION_LEAD_SECONDS=5
SIGNAL_MAXIMUM_ACTION_LEAD_SECONDS=10 (application default unless explicitly set)
```

Do not change these to make a deployment pass.

## First Boot

1. database created;
2. `alembic upgrade head` reaches `0006_bcgame_rounds`;
3. web deploy succeeds;
4. worker deploy succeeds;
5. `/ready` = 200;
6. `/health` shows:
   - topology `web-plus-dedicated-worker`;
   - product BTC/USD / BC_UPDOWN_5S / 5s / 1-50;
   - PAPER;
   - signals off;
   - fresh BTCUSDT external feed;
   - fresh worker heartbeat;
   - round sync disabled/not healthy yet;
7. `/market/status` explicitly labels BTCUSDT as external reference;
8. unauthenticated webhook POST rejected.

## Telegram Smoke Test — Signals Still Off

- `/start` new user sees guided registration, not main menu;
- registration → deposit → User ID → profile screenshot → deposit screenshot(s);
- verification packet reaches owner's private bot chat;
- owner approve/resubmit/reject controls work;
- resubmission preserves old packet;
- approved user menu contains:
  - `⚡ BTC 5s Signal`
  - `📈 My Results`
  - `ℹ️ How It Works`
  - `🆘 Support`;
- selecting BTC signal shows Start Rate → 5s → End Rate explanation first;
- `Scan Next Round` refuses because signals are off;
- no button wall before approval;
- no separate admin group requirement.

## Round-Sync Safety Test

After controlled signal gate is enabled for research but before a provider is integrated:

- `Scan Next Round` must say round timing is not synchronized;
- it must not create a directional waiting signal;
- it must not fall back to next-minute timing;
- it must not show BC.GAME execution button.

This is a **pass**, not a failure: fail-closed behavior is required.

## After BC.GAME Round Provider Is Integrated

Validate against live page before enabling LIVE:

- countdown/order-close timestamp;
- first flag Start Rate time;
- 5-second second flag End Rate time;
- exact Start/End values;
- stake band;
- payouts/pools where available;
- snapshot freshness;
- round IDs do not duplicate;
- round rows persist in `bcgame_rounds`;
- signal row links to correct round;
- Telegram direction arrives only with 5-10 seconds remaining (initial research window);
- activation notification occurs after lock and never says `ENTER NOW`.

## PAPER Presentation

PAPER must never show:

- `ENTER NOW`;
- actionable BC.GAME button;
- claim that Binance reference result equals BC.GAME result.

PAPER may show external-reference result only with explicit diagnostic wording.

## Database / Retention

10-day cleanup applies to temporary webhook receipts, notification receipts and completed broadcast deliveries.

Do not clean automatically:

- users/approval;
- verification history;
- `bcgame_rounds`;
- signals/results;
- broadcast summaries;
- meaningful audit history.

## GitHub Actions

Both repository workflows are intentionally removed/disabled. Do not recreate them while the owner has asked not to use GitHub Actions. Use Render logs, migrations, health endpoints and manual/runtime smoke tests.

## Free Database Upgrade

Upgrade the same database before expiry (target around day 25-28), then recheck:

- `/ready`;
- worker heartbeat;
- user approvals;
- verification history;
- BC.GAME round rows;
- signal history.

## Stop Conditions

Stop and repair if:

- migration error;
- old 300-second/next-minute timing appears anywhere in runtime behavior;
- stale worker/market/round data allows a signal;
- direction arrives too early or too late outside action window;
- activation message encourages a late order;
- BC.GAME Start/End Rate is replaced by external price data;
- PAPER becomes actionable;
- verification goes anywhere except owner private bot chat;
- unauthorized user/admin access occurs;
- duplicate worker lifecycle processing occurs.
