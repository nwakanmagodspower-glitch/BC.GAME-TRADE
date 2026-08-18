# Database Model

PostgreSQL is the source of truth. Telegram messages are presentation only.

## Core Tables

### users

- `id`
- `telegram_user_id` unique
- `telegram_username`
- `first_name`
- `role` (`USER`, `ADMIN`, `OWNER`)
- `status`
- `created_at`
- `last_seen_at`
- `approved_at`
- `approved_by`
- `suspended_at`

### verification_requests

- `id`
- `user_id`
- `state`
- `bcgame_user_id`
- `submitted_at`
- `reviewed_at`
- `reviewed_by`
- `decision_reason`
- `attempt_number`

### verification_evidence

- `id`
- `verification_request_id`
- `kind` (`PROFILE_SCREENSHOT`, `DEPOSIT_SCREENSHOT`)
- Telegram file identifier / durable reference metadata
- `created_at`

Do not duplicate raw media unnecessarily. Preserve enough metadata to retrieve/forward evidence reliably while respecting Telegram/file-retention constraints.

### admin_actions

Audit log for approval, rejection, suspension, broadcast creation, strategy toggles, and corrections.

### signals

- `id`
- `requested_by_user_id`
- `pair`
- `product`
- `strategy_version`
- `decision`
- `created_at`
- `planned_entry_at`
- `entry_window_start`
- `entry_window_end`
- `expiry_at`
- `reference_entry_price`
- `reference_expiry_price`
- `quality_score`
- `confidence`
- `status`
- `market_snapshot_version`

### signal_features

Stores the compact feature snapshot needed to reproduce/explain a decision. Do not store unlimited raw tick streams here.

### signal_outcomes

- `signal_id` unique
- `outcome` (`WIN`, `LOSS`, `TIE`, `CANCELLED`, `UNRESOLVED`)
- `resolved_at`
- `resolver_source`
- `notes`

Normal outcomes are append-once/immutable. Any correction requires a separate audited correction record.

### broadcasts

- `id`
- `created_by`
- `body`
- `created_at`
- `recipient_count`
- `sent_count`
- `failed_count`
- `status`

### broadcast_deliveries

One row per recipient with delivery status, enabling retry/idempotency.

### system_settings

Versioned operational values such as active strategy, signal mode, kill-switch state, and configurable expiry. Sensitive secrets do not belong here.

## Integrity Rules

- Telegram user ID is the durable user identity.
- One active verification request per user unless a resubmission flow explicitly creates a new attempt.
- Admin callbacks must be idempotent.
- Approval survives application restarts/deployments.
- Signal IDs are immutable.
- Historical strategy versions are never rewritten.
- All stored timestamps use UTC; user-facing display may convert to Africa/Lagos or configured locale.
- Database constraints should enforce uniqueness and state invariants where practical.