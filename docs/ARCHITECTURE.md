# Architecture

## System Shape

```text
Telegram
   ↓
Web/API Service (Render)
   ├─ Telegram webhook / onboarding / admin
   ├─ On-demand scan orchestration
   └─ Lightweight BTC market feed/cache
        ↓
PostgreSQL ← dedicated worker heartbeat
        ↑
Background Worker (Render)
   ├─ Lightweight BTC market feed/cache
   ├─ Entry-time revalidation
   ├─ Signal activation/cancellation
   ├─ Exact-window settlement
   ├─ Lifecycle notifications
   ├─ Broadcast delivery
   └─ Retention cleanup
```

Signal intelligence remains an application/core service used by the web for the initial scan and by the worker for pre-entry revalidation.

## Permanent Boundaries

### Telegram Layer

Owns commands, callback handling, message formatting, media intake, and admin controls. It must not contain trading logic.

### Application Layer

Owns user state transitions, permissions, verification workflow, scan orchestration, broadcast orchestration, and idempotency.

### Signal Intelligence Layer

Owns BTC/USDT Up/Down analysis only. It receives normalized market snapshots and returns structured decisions.

### Integration Layer

- Market data providers: Binance first, with replaceable interfaces.
- BC.GAME adapter: product identity and configurable registration/deposit/Up-Down destinations; future live BC.GAME reference-price/payout/pool/timing integration belongs here.
- Telegram adapter/application boundary.

## On-Demand Design

Signals are not generated continuously per user. The Web/API maintains one process-local BTC market feed/cache used by all on-demand scan requests handled by that process. The dedicated worker maintains its own lightweight process-local feed/cache for entry revalidation and expiry settlement. Redis/shared cross-process cache is deliberately deferred for V1.

The web must not create a directional waiting signal in the separated production topology when the dedicated-worker heartbeat is stale.

## Signal Decision Contract

```text
UP | DOWN | NO_TRADE | UNAVAILABLE
```

A directional signal must include signal ID, pair, product, strategy version, creation time, planned entry, entry validity window, expiry, direction, quality metadata, and invalidation policy/evidence.

## Lifecycle Contract

1. Initial on-demand scan creates a directional candidate only when data and strategy gates pass.
2. The worker must never activate it before the exact planned `entry_at` timestamp.
3. Before activation, the worker reruns V1 intelligence. `UNAVAILABLE`, `NO_TRADE`, or a direction change cancels the candidate.
4. Entry must occur no later than `entry_window_end`; otherwise cancel.
5. At expiry, settlement may use only a fresh reference event at or after `expiry_at` and inside the configured small settlement window.
6. If an exact-enough reference cannot be captured, mark the signal `EXPIRED`/unresolved rather than fabricating WIN/LOSS/TIE from a materially late price.

## Render Topology

### Web Service

- Telegram webhook endpoint
- onboarding/admin/application requests
- on-demand BTC scans
- health/readiness endpoints
- lightweight market feed/cache

### Background Worker

- independent lightweight market feed/cache
- candidate revalidation before entry
- outcome settlement
- lifecycle notifications
- broadcast queue delivery
- 10-day temporary-record cleanup

A PostgreSQL advisory leader lock protects singleton background jobs during Render deployment overlap. The worker writes a heartbeat to PostgreSQL; the web checks that heartbeat before accepting production signal requests.

### PostgreSQL

Persistent source of truth for users, onboarding/evidence metadata, admin actions, signals, outcomes, broadcasts, runtime settings, worker heartbeat, and audit state. Raw market streams are not stored indefinitely.

Redis is optional for V1. Add it only when queue/cache pressure or horizontal scaling justifies it.

## Failure Philosophy

Fail closed:

- stale data → no signal
- provider unhealthy → no signal
- dedicated worker unhealthy → no new directional signal
- strategy disabled → no signal
- unsupported pair/product → no signal
- onboarding incomplete → no access
- verification uncertain → remain pending
- missed reliable expiry reference → unresolved/EXPIRED, not guessed result

Do not substitute stale decisions or materially late prices when timing/freshness guarantees fail.
