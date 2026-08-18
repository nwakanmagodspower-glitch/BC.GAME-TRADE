# Milestones

No milestone may silently expand V1 scope beyond BTC/USDT + BC.GAME Up/Down.

## M0 — Architecture and Rules

- README
- AGENTS rules
- product specification
- architecture
- database model
- security rules
- strategy rules
- Render deployment plan

**Exit:** repository has an agreed source of truth before code.

## M1 — Application Foundation

- Python application skeleton
- configuration validation
- PostgreSQL connection
- migrations
- logging
- `/health` and `/ready`
- Render-compatible Docker/runtime packaging

**Exit:** service boots safely with signals disabled.

## M2 — Telegram + Guided Onboarding

- webhook handler
- `/start`
- sequential registration flow
- deposit guidance
- profile/user-ID capture
- deposit screenshot capture
- no normal menu before approval

**Exit:** complete verification request persists correctly.

## M3 — Admin Verification

- immediate admin verification packet
- approve/reject/resubmission callbacks
- affiliate-check workflow support
- persistent approval memory
- role/access enforcement
- audit log

**Exit:** approved users unlock normal menu; all other states remain gated.

## M4 — Market Data Foundation

- BTC/USDT provider abstraction
- initial provider implementation
- shared fresh market snapshot/cache
- provider health and freshness checks

**Exit:** no stale snapshot can pass readiness for signal generation.

## M5 — Signal Intelligence V1

- feature engine: trend, momentum, structure, volume, volatility, support/resistance
- market regime gate
- scoring/decision contract
- `UP`, `DOWN`, `NO_TRADE`, `UNAVAILABLE`
- immutable strategy version

**Exit:** deterministic paper decisions can be reproduced from stored feature snapshots.

## M6 — Timing and Invalidation

- planned entry calculation
- entry window
- expiry calculation
- pre-entry revalidation
- cancellation state

**Exit:** stale/invalidated candidates cannot become active signals.

## M7 — Outcome and Evaluation

- reference entry/expiry price capture
- automatic outcome resolver
- immutable outcome records
- strategy statistics

**Exit:** paper signals settle automatically and performance is queryable.

## M8 — Approved User Signal UX

- minimal main menu
- BTC signal request
- scan status
- formatted signal/no-trade result
- user result history
- support/how-it-works

**Exit:** approved beta user can complete the full on-demand flow without seeing backend complexity.

## M9 — Broadcast and Admin Operations

- approved-user broadcast
- controlled batching/retries
- delivery records
- user suspension
- system/strategy status
- owner kill switch controls

**Exit:** broadcasts do not interfere with signal latency or availability.

## M10 — Render Production Packaging

- web service
- background worker
- PostgreSQL
- environment-variable contract
- health/readiness
- migration/startup procedure
- smoke tests

**Exit:** Render production deployment runs with `SIGNAL_MODE=PAPER` and `SIGNALS_ENABLED=false` until explicitly enabled.

## M11 — Paper Production Validation

- real live market feed
- on-demand paper scans
- entry/expiry timing validation
- outcome reconciliation
- failure/latency observations

**Exit:** technical correctness is demonstrated under real runtime conditions.

## M12 — Controlled Live Beta

- explicitly enable live signal presentation
- manual execution only
- small manually verified user cohort
- monitor data health, no-trade rate, timing, outcomes, and support issues

**Exit:** stable production operation with evidence sufficient to decide next strategy iteration.

## M13 — Refinement, Not Scope Explosion

Possible improvements only after evidence:

- order flow/order book
- better probability calibration
- BC.GAME reference-price adapter
- payout/pool/EV gate
- improved timing model

Additional coins or products require a separate explicit milestone and should not be bundled into ordinary refinement.