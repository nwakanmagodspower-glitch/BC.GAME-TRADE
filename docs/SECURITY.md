# Security and Authenticity Rules

## Trust Model

The system does not trust Telegram message state, user claims, filenames, or screenshots by themselves. Backend records and explicit admin decisions are authoritative.

## Verification Evidence

The bot accepts user-supplied profile/user-ID evidence and deposit screenshot(s) only as evidence for manual review. The backend must:

- bind each evidence item to one verification request and Telegram user;
- reject unsupported/oversized inputs according to configured limits;
- bound deposit evidence count and rate before persistence;
- preserve submission order and timestamps;
- prevent one user's evidence from being attached to another user's request;
- make admin callbacks idempotent;
- retain an audit trail for resubmissions and decisions.

The bot must never claim that screenshots alone prove affiliate attribution. Admin checks the affiliate dashboard and makes the final decision.

## Telegram Webhook

- Validate Telegram webhook secret.
- Reject unexpected HTTP methods/content types.
- Treat callback data as untrusted input.
- Authorize every admin action server-side; never rely on whether a button was visible.
- Rate-limit abuse-sensitive routes/actions.
- Mark an update successful only after handlers complete; failed processing must remain retryable.

## Authorization

Roles: `USER`, `ADMIN`, `OWNER`.

Every protected action must check persisted role/status. Suspended or blocked users cannot request signals even if they reuse an old callback.

Authorization and kill-switch state are rechecked after asynchronous analysis and immediately before signal persistence. Broadcast and notification workers recheck approval/block state at delivery time.

## Secrets

Never commit:

- Telegram bot tokens
- webhook secrets
- database passwords
- provider credentials
- private affiliate/admin credentials

Use Render environment variables/secrets.

## Logging

Do not log secrets, full tokens, or unnecessary sensitive evidence. Logs should contain stable internal IDs and enough operational context for debugging.

## Signal Integrity

- Stale data cannot produce a directional signal.
- A signal record is created before it is presented to a user.
- Strategy version and timestamps cannot be silently changed after issuance.
- Settlement corrections require an audited correction path.
- Manual admin actions must record actor and timestamp.

## Operational Safety

- Health/readiness checks are separate.
- Market-provider failure disables signal generation, not onboarding/support.
- Broadcast failures do not block signal requests.
- Verification packets and broadcasts are delivered by bounded background workers rather than the webhook path.
- Database failure fails closed for access and signal issuance.
- Kill switches must be owner-controlled and persistent/configurable.

## Scope Safety

V1 performs no automatic BC.GAME trade execution and handles no BC.GAME account passwords. The signal assistant is intentionally separated from user funds and execution.
