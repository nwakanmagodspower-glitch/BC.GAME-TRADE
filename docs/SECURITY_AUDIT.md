# Focused Security Audit

Date: 2026-08-22

Scope: DeTrade authorization/timer code, FastAPI/Telegram entry points, owner authorization, verification evidence, market-provider boundaries, storage/retention, concurrency, migrations, and Render configuration.

## Resolved findings

### SEC-01 — Placeholder accepted by deployment validation (high)

Affected/fixed locations: `render.yaml:49`, `app/integrations/detrade_token_provider.py:12`, `app/core/startup.py:132-144`.

`render.yaml` supplied `DETRADE_WS_TOKEN=temporary`, while startup checked only whether the value was non-empty. The Blueprint now declares the value as private/user-supplied, the provider and startup validation reject known placeholders, HYBRID warns/falls back, and AUTO fails closed.

### SEC-02 — Expired token could be revived in-process (high)

Affected/fixed locations: `app/integrations/detrade_token_provider.py:57`, `app/integrations/detrade_observer.py:251,303`.

The environment provider previously allowed `force_refresh=True` to reactivate the same rejected environment token. An environment value cannot rotate inside a running Render container. Invalidation is now permanent for that provider instance and auth failures also clear the last observation. Rotation requires replacing the Render secret and restarting.

### SEC-03 — Post-analysis timer depended on wall clock (high)

Affected/fixed locations: `app/integrations/detrade_observer.py:56-67`, `app/integrations/bcgame_rounds.py:20-33,150`, `app/services/signal_records.py:92`.

The server-derived deadline was converted to a timestamp and later compared with the machine clock. The snapshot now carries the monotonic deadline derived from the received `currentTime` and `priceStartTime`; both initial and post-analysis checks continue against monotonic elapsed time.

### SEC-04 — Public API documentation in production (low)

Affected/fixed location: `app/main.py:53-59`.

FastAPI Swagger, ReDoc, and OpenAPI routes are now disabled in production. Development keeps them for local work.

### SEC-05 — Human-entry margins too permissive (medium)

Affected/fixed locations: `app/core/config.py:58-60`, `render.yaml:65-70`.

Defaults increased from 7.0s/4.5s to 10.0s before analysis and 8.0s after analysis. This does not guarantee user latency; any delayed user is still instructed to skip.

### SEC-06 — Orphan synchronized round rows were unbounded (medium)

Affected/fixed locations: `app/services/retention_cleanup.py:29-38,79-104`.

The ten-day cleanup removed old signals but left their synchronized BCGAME round rows. Cleanup now removes only old round rows that have no remaining signal reference, after signal deletion. Recent or referenced rows remain intact.

### SEC-07 — Concurrent first insert for one external round could fail (medium)

Affected/fixed locations: `app/services/signal_records.py:43-53`.

Different users can receive the same new round concurrently. Round creation now uses a nested transaction/savepoint and reuses the unique-key winner, preventing one insert race from aborting the surrounding signal transaction.

## Verified controls

- WebSocket connection exceptions and operator status expose generic error codes, never credential-bearing URLs.
- Normalized timer output contains only round ID/status/phase/times/age/canTrade.
- Telegram webhook requires a constant-time compared secret header, exact JSON content type, body-size bound, valid integer update ID, idempotent receipt, processing timeout, per-user rate limit, and process concurrency bound.
- Owner/admin actions require the configured owner user and matching private chat, then re-authorize server-side.
- Verification photos are Telegram file IDs, count/rate/declared-size bounded, associated with one request/user, delivered by a retrying worker, and purged with BCGAME account ID after decision.
- Provider base URLs are validated as credential-free HTTPS/WSS and Binance/DeTrade hosts are allowlisted at startup, reducing SSRF risk.
- Market REST responses and WebSocket frames are size-bounded; stale/future/sparse market data fails closed.
- A shared observer and single-flight probe avoid per-user DeTrade connections. Scan coalescing, cooldown, DB row locks, a partial unique current-signal index, webhook backpressure, and advisory-locked background jobs constrain races and bursts.
- No automatic real-money execution, BCGAME password, browser cookie, JWT, access code, or session is handled by the application.
- Production uses PostgreSQL, migrations run before deploy, and no schema change was required for this timer hardening.

## Residual risks and operational requirements

- DeTrade is an undocumented third-party protocol. Fields/statuses may change; unknown values correctly fail closed, but operator monitoring remains necessary.
- Exact token TTL and an unattended official refresh grant are unverified. Manual secret rotation is required for synchronized timing.
- Telegram `file_size` is sender metadata; the bot never downloads evidence, so the configured limit mainly bounds accepted metadata/workflow. Telegram controls the hosted object.
- Rate limits are process-local. At horizontal scale, database invariants remain durable, but a shared external rate limiter would be appropriate before sustained 1,000-user burst traffic.
- `/health` intentionally exposes non-secret operational state and live round metadata. It exposes no authorization or exception details.

No unresolved critical or high-severity source vulnerability was found after the fixes above.
