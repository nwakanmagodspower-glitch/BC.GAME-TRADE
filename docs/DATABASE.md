# Database Model

PostgreSQL is the persistent source of truth for user access state and recent signal intelligence. Telegram messages and live market caches are presentation/operational state only.

## Core Tables

### `users`

Telegram identity, approval/access state, onboarding position, owner/admin metadata and timestamps.

After owner approval, the durable verification truth is the user's approved status plus approval metadata such as `approved_at` and `approved_by`.

### `verification_requests`

Verification evidence is temporary operational data used only to complete owner review.

During collection/review a packet may temporarily contain:

- BC.GAME User ID;
- Telegram profile screenshot file ID;
- Telegram deposit screenshot file ID(s);
- submission/delivery state.

Once the owner makes a final decision (approve, reject or resubmit), the BC.GAME User ID and Telegram evidence file IDs are purged immediately. They are not retained as permanent user history.

`verification_deliveries` is the temporary durable owner-inbox outbox. Owner review is unavailable until the complete packet is marked delivered. The delivery row is removed after the owner decision.

### `bcgame_rounds`

Compact, trustworthy BCGAME Up/Down round data from authenticated synchronized timing:

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

Do not create synthetic MANUAL_SYNC round rows. Do not store every BTC tick/order-book update here.

BC.GAME Start Rate and End Rate are product-truth fields and must never be filled with Binance values merely because BC.GAME data is missing.

### `signals`

Each generated scan/decision stores recent intelligence needed for strategy evaluation and operations:

- requesting user;
- game market/product;
- immutable strategy version;
- UP/DOWN/NO_TRADE decision;
- creation/timing metadata;
- external reference entry/end prices for diagnostics;
- compact feature snapshot;
- lifecycle/result status;
- decision/cancellation reason.

Signals/results are intentionally temporary intelligence records. In V1, every generated signal has a **10-day lifetime** and is deleted automatically after the retention cutoff.

External reference fields are diagnostic until BC.GAME settlement matching is verified.

### `signal_notifications`

Temporary idempotency/retry evidence for lifecycle notifications. These are deleted at or before the same 10-day retention boundary.

### `broadcasts`

Broadcast summary/body/status/counts.

### `broadcast_deliveries`

Per-recipient operational delivery state. Completed old rows are temporary and eligible for cleanup.

### `runtime_settings`

Operational toggles and worker heartbeat. Secrets do not belong here.

### `audit_logs`

Owner/admin changes and important operational actions. Do not place verification screenshots, deposit evidence or BC.GAME account IDs in audit details.

## Raw Market Data Policy

Live trade ticks/order-book data stay in bounded in-memory buffers for signal calculation. Do not allow continuous raw market data to accumulate in the primary PostgreSQL database.

## 10-Day Cleanup

The V1 cleanup window is 10 days.

Age-based cleanup applies to:

- generated signals/results;
- signal notification/delivery rows;
- Telegram webhook duplicate receipts;
- completed broadcast-delivery rows;
- other temporary operational records.

Verification evidence is even shorter-lived: BC.GAME User ID and Telegram screenshot file IDs are purged immediately after the owner decision rather than waiting 10 days.

The cleanup does not delete the user's approved/access state.

## Growth Expectations

For 0-250 users, persistent user rows are negligible. Because generated signal intelligence expires after 10 days and raw tick data is not stored, PostgreSQL growth is deliberately bounded.

Directional synchronized scans reuse the unique external round row. NO TRADE scans retain only lightweight metadata and do not create round rows, preventing continuous round-row growth.

## Integrity Rules

- Telegram user ID is durable user identity.
- Approval status is durable; verification evidence is temporary.
- BC.GAME User IDs and screenshot file IDs are not retained after review.
- Generated signal intelligence expires after 10 days.
- `external_round_id` is unique when BC.GAME supplies one.
- Historical strategy identity is immutable during a signal's lifetime.
- BC.GAME actual direction is derived from actual BC.GAME Start/End Rate, not external exchange references.
- Unknown outcome remains unresolved.
- All timestamps are stored in UTC.
- Admin callbacks and deliveries are idempotent.
