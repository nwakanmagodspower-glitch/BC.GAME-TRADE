# Database Model

PostgreSQL is the persistent source of truth. Telegram messages and live market caches are presentation/operational state only.

## Core Permanent Tables

### `users`

Telegram identity, approval/access state, onboarding position, owner/admin metadata and timestamps.

### `verification_requests`

Each evidence packet stores BC.GAME User ID, Telegram profile/deposit file references, submission/review state and reviewer metadata. Resubmission preserves the prior reviewed row and creates a new packet rather than overwriting history.

Evidence is bounded to a configured small count/size and rate. `verification_deliveries` is the durable owner-inbox outbox; owner review is unavailable until the complete packet is marked delivered.

### `bcgame_rounds`

One compact row per observed BC.GAME Up/Down round:

- `external_round_id`
- `game_market` (`BTC/USD`)
- `duration_seconds` (`5` for V1)
- `stake_band` (`1-50` for V1)
- `observed_at`
- `order_closes_at`
- `start_rate_at`
- `end_rate_at`
- `start_rate`
- `end_rate`
- `actual_direction`
- UP/DOWN payout percentages
- UP/DOWN pool amounts
- UP/DOWN player counts
- source/raw metadata

This table is intentionally compact. Do **not** store every BTC tick/order-book update here.

BC.GAME Start Rate and End Rate are product-truth fields and must never be filled with Binance values merely because BC.GAME data is missing.

### `signals`

Each scan/decision stores:

- requesting user
- optional `bcgame_round_id`
- game market/product
- immutable strategy version
- UP/DOWN/NO_TRADE decision
- creation time
- BC.GAME Start Rate time (`entry_at`) when synchronized
- order-close timestamp (`entry_window_end`) when synchronized
- BC.GAME End Rate time (`expiry_at`) when synchronized
- external reference entry/end prices for diagnostics
- compact feature snapshot
- lifecycle/result status
- decision/cancellation reason

The original strategy `decision_reason` is immutable after issuance. Later lifecycle diagnostics use `status_reason`. A per-user scan timestamp supports abuse throttling; the issuance transaction locks the user and rechecks access and kill switches after asynchronous analysis.

External reference fields are diagnostic until BC.GAME settlement matching is verified.

### `signal_notifications`

Idempotency/retry evidence for lifecycle notifications. Temporary delivery records may be cleaned after the retention window; the signal/result remains.

### `broadcasts`

Permanent broadcast summary/body/status/counts.

### `broadcast_deliveries`

Per-recipient operational delivery state. Completed old rows are temporary and eligible for cleanup.

### `runtime_settings`

Operational toggles and worker heartbeat. Secrets do not belong here.

### `audit_logs`

Owner/admin changes, access decisions, signal toggles and other important administrative actions.

## Raw Market Data Policy

Live trade ticks/order-book data stay in bounded in-memory buffers for signal calculation. If historical high-frequency research storage is later required, use a deliberate research dataset/storage design instead of allowing the primary application PostgreSQL database to grow without limit.

## 10-Day Temporary Cleanup

Age-based cleanup applies to temporary operational data such as:

- Telegram webhook duplicate receipts;
- old notification-delivery receipts;
- completed broadcast-delivery rows.

It does **not** delete:

- users/approval state;
- verification history;
- BC.GAME round research/result rows;
- signals and results;
- broadcast summaries;
- runtime configuration currently needed;
- meaningful audit history.

Webhook receipts retain processing outcome and attempt metadata until the temporary-record cutoff, so only successfully completed updates are treated as duplicates.

## Growth Expectations

For 0-250 users, user rows are negligible. The meaningful long-term growth becomes signals plus observed BC.GAME round records. A round row is small because it stores timestamps/rates/pool summary rather than raw tick streams.

If every BC.GAME round is eventually captured continuously, round-table growth should be monitored separately from user-generated signals and older research rows may later be archived by month/strategy version rather than blindly deleted.

## Integrity Rules

- Telegram user ID is durable user identity.
- `external_round_id` is unique when BC.GAME supplies one.
- One signal may point to one BC.GAME round.
- Historical strategy identity is immutable.
- BC.GAME actual direction is derived from actual BC.GAME Start/End Rate, not external exchange references.
- Unknown outcome remains unresolved.
- All timestamps are stored in UTC.
- Admin callbacks and deliveries are idempotent.
