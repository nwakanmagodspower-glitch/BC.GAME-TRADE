# Architecture

## System Shape

```text
Telegram
   ↓
Web/API Service (Render)
   ↓
Application Services
   ├─ Onboarding / Verification
   ├─ Access Control
   ├─ Signal Request Service
   ├─ Broadcast Service
   └─ Admin Service
        ↓
Signal Intelligence Core
   ├─ Market Data Adapter
   ├─ Feature Engine
   ├─ Strategy / Scoring
   ├─ Timing Engine
   ├─ Invalidation Engine
   └─ Outcome Resolver
        ↓
PostgreSQL
```

A background worker handles market feed maintenance, delayed entry checks, settlement, and broadcast delivery.

## Permanent Boundaries

### Telegram Layer

Owns commands, callback handling, message formatting, media intake, and admin controls. It must not contain trading logic.

### Application Layer

Owns user state transitions, permissions, verification workflow, scan orchestration, broadcast orchestration, and idempotency.

### Signal Intelligence Layer

Owns BTC/USDT Up/Down analysis only. It receives normalized market snapshots and returns structured decisions.

### Integration Layer

- Market data providers: Binance first, with replaceable interfaces.
- BC.GAME adapter: future live reference-price/payout/pool/timing integration.
- Telegram adapter.

## On-Demand Design

Signals are not generated per user continuously. A shared BTC market-data cache is maintained. When an approved user requests a scan, the system evaluates the latest valid snapshot.

## Signal Decision Contract

```text
UP | DOWN | NO_TRADE | UNAVAILABLE
```

A directional signal must include:

- signal ID
- pair
- product
- strategy version
- created timestamp
- planned entry timestamp
- entry window
- expiry timestamp
- direction
- quality/confidence metadata
- invalidation policy

## Render Topology

### Web Service

- Telegram webhook endpoint
- health/readiness endpoints
- lightweight API endpoints

### Background Worker

- market data feed/cache upkeep
- candidate revalidation before entry
- outcome settlement
- broadcast queue delivery

### PostgreSQL

Persistent source of truth for users, onboarding, evidence metadata, admin actions, signals, outcomes, broadcasts, and settings.

Redis is optional for V1. Add it only when queue/cache pressure justifies it.

## Failure Philosophy

Fail closed:

- stale data → no signal
- provider unhealthy → no signal
- strategy disabled → no signal
- unsupported pair/product → no signal
- onboarding incomplete → no access
- verification uncertain → remain pending

Do not substitute cached/stale decisions when freshness guarantees fail.