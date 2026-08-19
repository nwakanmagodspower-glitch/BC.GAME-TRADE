# Architecture

## System Shape

```text
Telegram
   ↓
Web/API Service (Render)
   ├─ Telegram webhook / onboarding / owner verification
   ├─ Manual 15/14/13/12 countdown confirmation
   ├─ On-demand five-second signal orchestration
   ├─ Continuous BTCUSDT tick cache + cached 1m context
   └─ Health/readiness + worker/timing status
        ↓
PostgreSQL ← dedicated worker heartbeat
        ↑
Background Worker (Render)
   ├─ Independent lightweight BTCUSDT feed/cache
   ├─ diagnostic Start/End reference lifecycle
   ├─ durable owner verification-packet delivery
   ├─ future AUTO_SYNC integration boundary
   ├─ broadcast delivery
   └─ 10-day temporary-record cleanup
```

## Real BC.GAME Product Contract

Target: **BTC/USD • Up/Down • 5 seconds • initial $1-50 band**.

```text
15-second order countdown
        ↓
orders lock / first flag
        ↓
BC.GAME Start Rate
        ↓
5 seconds
        ↓
second flag
        ↓
BC.GAME End Rate
        ↓
End > Start => UP wins
otherwise => DOWN wins per supplied rules
```

The order countdown is the human analysis/action period; the subsequent five seconds is the result-measurement period.

## Timing Architecture

### MANUAL_SYNC — active V1

The user prepares BC.GAME and enters the stake first. When the fresh countdown displays 15, 14, 13, or 12 seconds, the user taps the matching Telegram button. The web process timestamps the tap and creates a synthetic timing snapshot:

```text
observed tap time
+ confirmed remaining countdown
= estimated Start Rate time
+ 5 seconds
= estimated End Rate time
```

These are estimates and must never be represented as BC.GAME-issued timestamps or round IDs. The backend performs a post-computation remaining-time check and refuses the current round if too little time remains. Per-user database locking and a five-second cooldown prevent concurrent or repeated callbacks from creating multiple current signals.

### AUTO_SYNC — future upgrade

The BC.GAME/DeTrade adapter is reserved for a verified structured round source containing real countdown/round IDs/Start-End data. It can replace MANUAL_SYNC without changing Telegram onboarding, signal intelligence, database ownership or service topology.

## Permanent Boundaries

### Telegram Layer

Commands, callbacks, messages, evidence intake and owner controls. It never owns trading logic. Countdown buttons are user timing input, not strategy decisions.

### Application Layer

User state, permissions, verification, scan orchestration, idempotency, worker-health gating, timing checks and broadcasts.

### Signal Intelligence Layer

Predicts immediate BTC direction for a five-second target. Primary inputs are live tick velocity/acceleration, aggressive trade flow and micro-volatility. Slower 1-minute indicators are context only.

### Market Data Layer

Binance BTCUSDT is the initial external analysis/reference provider. One continuous stream/cache is shared by all requests in a process. Slow candle context is refreshed in the background; a button click does not download history. Near-simultaneous scans are coalesced so many users do not trigger duplicate market calculations.

### BC.GAME/DeTrade Layer

Future structured integration owns genuine round ID, countdown/order-close, Start Rate, End Rate, payouts, pools and player counts. Synthetic MANUAL_SYNC IDs do not enter the genuine `bcgame_rounds` table.

## On-Demand Flow

```text
User prepares BC.GAME + stake
        ↓
Telegram BTC 5s Signal
        ↓
15s | 14s | 13s | 12s
        ↓
access + worker + market + cached-context checks
        ↓
shared/coalesced five-second intelligence
        ↓
remaining-time check
        ↓
UP / DOWN / NO_TRADE / UNAVAILABLE
        ↓
manual execution before BC.GAME reaches 0
```

## Actionability Contract

A MANUAL_SYNC direction is actionable only when approved access, signal switch, worker heartbeat, fresh market feed and cached context are healthy; the user selected an allowed countdown; the five-second quality gate passes; and enough estimated time remains after calculation. Otherwise skip or return UNAVAILABLE.

## Signal Lifecycle

The actionable direction is delivered once from the web request path. Because the player may immediately place the order, the worker must not later reverse/cancel the delivered MANUAL_SYNC direction based on post-delivery revalidation. The worker may capture external Start/End reference prices for diagnostics. If those reference windows are missed, mark the diagnostic outcome unresolved rather than changing the original delivered direction.

Manual lifecycle notifications are suppressed to prevent synchronized Telegram message bursts; status is retained in PostgreSQL and can be viewed through My Results/admin tools. When AUTO_SYNC later supplies exact BC.GAME outcome data, exact product results can replace external diagnostic labels.

## Payout / Pool / Copy Trade

Direction prediction and payout economics remain separate. Pool/player/leaderboard data are research-only until statistically validated. **Copy Top Trade is not part of V1.**

## Render Topology

### Web — Starter

Telegram, onboarding, owner verification, timing buttons, scan orchestration, health, continuous BTC feed/cache.

### Worker — Starter

Diagnostic lifecycle, broadcasts, heartbeat and retention cleanup. PostgreSQL advisory locking protects singleton jobs during overlapping deploys.

### PostgreSQL

Persistent users, verification history, signals, settings, broadcasts and audit state. Raw tick streams remain in memory. Free PostgreSQL is PAPER-validation-only: it expires after 30 days and has no backups. Upgrade the same database to a paid Basic plan before admitting controlled-beta users.

Authenticated Telegram updates carry PROCESSING/SUCCEEDED/FAILED receipt state so failures remain retryable. Verification submission creates a durable delivery row in the same transaction; the worker sends bounded evidence first and exposes owner decision buttons only after the evidence send succeeds.

## Scaling

The engine is intentionally shared rather than per-user: one BTC stream, one cached candle context and coalesced scans. This makes **10-100 users a comfortable initial validation target** and is designed to be evaluated toward **250 active users** on the current topology.

`1,000` synchronized users must not be claimed as proven on the initial Starter topology. Reaching that level requires measured Render/Telegram load tests and may require additional web instances, shared cache/queueing and Telegram delivery tuning. The architecture preserves that upgrade path without changing the signal model.

## Failure Philosophy

Fail closed:

- stale BTC feed/cache => UNAVAILABLE
- worker unhealthy => no new signal
- invalid countdown input => no signal
- calculation leaves too little time => skip round
- ambiguous microstructure => NO_TRADE
- missing external diagnostic Start/End reference => unresolved, never fabricated
- AUTO_SYNC selected without a verified provider => unavailable
