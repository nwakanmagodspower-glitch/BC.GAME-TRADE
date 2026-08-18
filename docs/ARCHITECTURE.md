# Architecture

## System Shape

```text
Telegram
   ↓
Web/API Service (Render)
   ├─ Telegram webhook / onboarding / owner verification
   ├─ On-demand "Scan Next Round" orchestration
   ├─ Lightweight BTCUSDT analysis feed/cache
   └─ Health/readiness + worker/round-sync status
        ↓
PostgreSQL ← dedicated worker heartbeat
        ↑
Background Worker (Render)
   ├─ Lightweight BTCUSDT analysis feed/cache
   ├─ BC.GAME round-state integration boundary
   ├─ Start-Rate-time revalidation
   ├─ 5-second lifecycle/reference settlement
   ├─ Notifications
   ├─ Broadcast delivery
   └─ 10-day temporary-record cleanup
```

## Real BC.GAME Product Contract

The target product is BC.GAME Up/Down displayed as **BTC/USD** with a **5-second** duration. V1 initially targets the visible `$1-50` band.

Round flow:

```text
BC.GAME order countdown
        ↓
orders lock / first flag
        ↓
BC.GAME records Start Rate
        ↓
5 seconds
        ↓
second flag
        ↓
BC.GAME records End Rate
        ↓
End > Start => UP wins
otherwise => DOWN wins per supplied game instructions
```

The order-countdown period is an analysis/action window; it is not the 5-second result-measurement period.

## Permanent Boundaries

### Telegram Layer

Commands, callbacks, messages, evidence intake, owner controls. It must never implement trading logic. Time-sensitive signal messages stay concise.

### Application Layer

User state, permissions, verification workflow, scan orchestration, idempotency, worker-health gating, human-action lead-time checks, broadcasts.

### Signal Intelligence Layer

Predicts the immediate BTC direction relevant to the 5-second target. Primary inputs are tick momentum/acceleration, aggressive trade flow, micro-volatility and later order-book/microprice data. Slower 1-minute indicators provide context only.

### BC.GAME Round Layer

Owns structured BC.GAME round data when a legitimate reliable source is integrated:

- round ID
- order-close timestamp/countdown
- Start Rate timestamp/value
- End Rate timestamp/value
- stake band
- UP/DOWN payout
- pool amounts/player counts

No other layer may invent round timing from wall-clock minute boundaries. Screen scraping is not the default architecture when a structured source can be integrated.

### Market Data Layer

Binance BTCUSDT is the initial external analysis/reference provider. Provider interfaces remain replaceable. External prices must never be described as BC.GAME settlement truth until measured against BC.GAME Start/End Rate.

## On-Demand Design

There is no continuous signal generation per user. One process-local BTC feed serves all scan requests on the web process; the worker has its own lightweight feed for revalidation/reference lifecycle work.

A user request is:

```text
BTC 5s Signal
   ↓
show game context
   ↓
Scan Next Round
   ↓
access + kill switch + worker + market + round-sync checks
   ↓
UP / DOWN / NO_TRADE / UNAVAILABLE
```

## Actionability Contract

A directional signal is actionable only when:

1. the user is approved and active;
2. signals are enabled;
3. worker heartbeat is fresh;
4. BTC market data is fresh;
5. BC.GAME round state is trustworthy/fresh;
6. the round matches `BTC/USD`, `5s`, `$1-50` V1 scope;
7. enough time remains before BC.GAME closes the order window for a human to act;
8. quality thresholds are met.

If any of these fail, do not generate an actionable direction.

## Signal Lifecycle

1. During BC.GAME order countdown, user requests next-round scan.
2. Candidate uses the synchronized round's first-flag timestamp as `entry_at` and second-flag timestamp as `expiry_at`.
3. Before Start Rate time, the worker may revalidate/cancel if direction quality changes.
4. At Start Rate time, external BTC data may be recorded as a diagnostic reference; BC.GAME Start Rate remains product truth.
5. Five seconds later, external reference may be recorded for PAPER diagnostics.
6. When reliable BC.GAME Start/End Rate ingestion exists, BC.GAME values become the outcome label.
7. Missing trustworthy result data => unresolved/EXPIRED, never guessed.

## Payout / Pool Architecture

Direction prediction and economics stay separate:

```text
Direction model => probability/quality of UP or DOWN
Payout model    => whether displayed return makes the opportunity worthwhile
```

UP/DOWN pool amounts, player counts and leaderboard data are collected only for research until evidence shows predictive value. Leaderboard copying is not part of V1 signal logic.

## Render Topology

### Web — Starter

Telegram, onboarding, owner verification, scan orchestration, web health, lightweight BTC feed.

### Worker — Starter

Round/lifecycle coordination, revalidation, notifications, broadcasts and cleanup. PostgreSQL advisory locking prevents duplicate singleton jobs during deployment overlap.

### PostgreSQL

Persistent users, verification history, signals/results, round metadata snapshots, settings, broadcasts and audit state. Raw tick/order-book streams are not retained indefinitely.

### Database plan

First month may use Render Free PostgreSQL for PAPER/research. Upgrade before expiry once production history becomes valuable.

## Scaling

0-250 users: current Web + Worker + PostgreSQL topology is sufficient for the planned on-demand model.

Later scale triggers:

- Redis/shared cache only when needed;
- more web instances only with stateless request handling;
- worker scaling only with explicit job partitioning/locks;
- high-frequency data should stay in memory/specialized storage rather than bloating main PostgreSQL.

## Failure Philosophy

Fail closed:

- stale analysis feed => UNAVAILABLE
- stale/missing BC.GAME round sync => no actionable signal
- worker unhealthy => no new signal
- insufficient action lead time => skip round
- ambiguous microstructure => NO_TRADE
- missing trustworthy Start/End Rate => unresolved, not fabricated
- PAPER mode => no execution button/instruction
