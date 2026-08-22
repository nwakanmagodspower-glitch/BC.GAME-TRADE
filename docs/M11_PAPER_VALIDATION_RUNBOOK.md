# Validation Runbook

This runbook supersedes the former manual-countdown-button procedure.

## PAPER validation

1. Set `SIGNAL_MODE=PAPER`, `SIGNALS_ENABLED=false`, and keep the same product identity.
2. Verify web/worker/database health, Telegram idempotency/backpressure, owner review, and ten-day cleanup.
3. Exercise `⚡ BTC 5s Signal`; PAPER output must not include an actionable BCGAME link or execution instruction.
4. Inspect external reference outcomes only as diagnostics. Do not label them as BCGAME results.

## HYBRID timer validation

1. Use a current private DeTrade token and restart the existing web service.
2. Send owner-only `/round_status` through at least five complete BTC/USD rounds.
3. Confirm changing round IDs, status `1001` during the visible betting window, countdown ending at `priceStartTime`, and an approximately 5000 ms evaluation window.
4. Remove/expire authorization and confirm the web service stays healthy and Scan Now falls back without inventing round metadata.
5. Restore authorization and inject/test stale, `1008`, unknown, late, and wrong-duration fixtures; each must fail closed.
6. Confirm a valid closed/late authoritative frame does not use fallback.

## Controlled LIVE gate

Before `SIGNALS_ENABLED=true`, require fresh worker/market/candle health, owner approval, correct BCGAME product setup, timing checks, cooldown, and post-analysis margin. A qualified user still places any direction manually. Stop LIVE delivery if timing, market data, worker state, access, or product identity is uncertain.
