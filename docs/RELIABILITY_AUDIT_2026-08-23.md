# Production Reliability Audit — 2026-08-23

## Outcome

This pass improves timing recovery, user-scan latency, readiness diagnostics, and regression coverage without changing the locked `BTC_ORIGINAL_INTELLIGENCE_TIMER_V1` prediction policy.

It does **not** claim perfect predictions or guaranteed wins. The application does not yet persist authoritative BCGAME Start Rate and End Rate labels for each prediction, so an evidence-backed real-product win rate cannot currently be calculated.

## Confirmed bottlenecks

1. A user scan could wait up to 2.5 seconds for a DeTrade frame. That is too much of a short BCGAME entry window.
2. The observer polled every 50 ms while waiting for a background frame.
3. Reconnect backoff was reset after sleeping, by which time a formerly fresh 1.5-second observation was necessarily stale. Repeated disconnects could therefore increase recovery delay even after a healthy session.
4. Health output did not distinguish exchange candle time from the time of the most recent successful cache refresh.
5. Operators had no single pre-recording check covering the live switch, Binance tick/candle state, trade-flow buffer, and authoritative BCGAME timer.
6. The baseline test suite had nine failures caused by tests that still asserted removed notification behavior, old UI copy, and an obsolete strategy identifier.

## Changes made

- User-facing timer probes now use a dedicated 1.0-second limit. Owner `/round_status` diagnostics retain the longer 2.5-second probe.
- New DeTrade observations wake waiting scans immediately through an event instead of 50 ms polling.
- Any session that delivered a valid observation resets reconnect backoff before the reconnect sleep.
- Authentication-failure paths also wake waiting probes and continue to invalidate the rejected environment token without printing it.
- Health output now includes non-secret candle refresh age and prediction-compute diagnostics.
- New owner-only `/preflight` command reports `READY TO SCAN` only when the live signal switch, market stream, candle cache, and configured timer path are ready. In synchronized modes, an unavailable/manual fallback timer is not considered recording-ready.
- Tests were aligned with the intentionally disabled lifecycle notifications, current `Scan Market` copy, and locked strategy identity.

## Validation evidence

- Full test suite: **83 passed**.
- Python bytecode compilation: passed.
- Alembic migration from an empty database through revision `0007_security_delivery_hardening`: passed.
- `render.yaml` parse: passed; two services and one database were recognized.
- Synthetic full prediction compute, 100 uncached runs with 60 closed candles and 500 recent trades:
  - median: 0.415 ms
  - p95: 1.261 ms
  - maximum: 1.505 ms
- A live local Binance warm-up could not be completed because this workstation's DNS resolver returned `getaddrinfo failed`. The application failed closed with `service_available=false` and emitted no direction. Render must therefore be checked independently after deployment.
- Ruff found pre-existing formatting and broad-exception warnings across the repository. They are not runtime failures and were not bulk-rewritten in this focused pass.

## Recording workflow

1. Confirm Render deployment is successful.
2. Check `/ready` and `/health`.
3. In the owner private Telegram chat, run `/round_status` to confirm a real DeTrade round and approximately five-second evaluation window.
4. Run `/preflight` immediately before recording.
5. Record a scan only when it says `READY TO SCAN`.
6. If the bot returns `NO TRADE`, present that as the safety behavior it is. Do not retry until a direction appears or imply that every round should be traded.
7. If `/preflight` says `WAIT`, skip the round. Do not use a promotional recording as a reason to bypass freshness or timing gates.

## Accuracy boundary and next evidence milestone

The current engine uses Binance BTCUSDT as external evidence; BCGAME BTC/USD Start Rate and End Rate remain the product truth. External-reference settlement must not be advertised as a verified BCGAME win rate.

The next accuracy milestone is a read-only, credential-safe BCGAME outcome collector that can reliably associate exact BCGAME Start/End values with the persisted round ID. Only after a sufficiently large out-of-sample labeled set exists should thresholds or features be compared. Until then, changing the scoring model would be unmeasured tuning and may make live performance worse.
