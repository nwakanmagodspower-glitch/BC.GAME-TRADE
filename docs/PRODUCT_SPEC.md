# Product Specification

## Product Definition

BC.GAME TRADE is an on-demand Telegram signal assistant specialized for **BTC/USDT on BC.GAME Up/Down**.

The V1 product does not attempt to scan every BC.GAME trading feature or every coin. It specializes deeply in one market and one contract type.

## User States

- `NEW`
- `ONBOARDING_REGISTRATION`
- `ONBOARDING_DEPOSIT`
- `ONBOARDING_PROFILE_PROOF`
- `ONBOARDING_DEPOSIT_PROOF`
- `PENDING_REVIEW`
- `APPROVED`
- `REJECTED`
- `RESUBMISSION_REQUIRED`
- `SUSPENDED`
- `BLOCKED`

## Guided Onboarding

The onboarding experience must be sequential. Do not show the normal bot menu before approval.

### Step 1 — Registration

The bot gives concise registration guidance and the configured BC.GAME affiliate/registration link.

The user proceeds explicitly to the next step.

### Step 2 — Deposit

The bot gives concise deposit guidance. Avoid unnecessary images or repeated promotional graphics.

### Step 3 — Profile/User ID Evidence

The bot asks the user to submit a screenshot of the relevant BC.GAME profile area showing the identifier needed for manual affiliate verification, and separately captures the textual user ID when possible.

### Step 4 — Deposit Evidence

The bot asks for deposit screenshot(s). The backend associates every file with the same verification request.

### Step 5 — Submission Validation

Before forwarding to admin, the backend verifies that the required fields/evidence exist:

- Telegram identity
- BC.GAME user ID or captured identifier
- profile/user-ID screenshot
- deposit screenshot(s)

This validation checks completeness, not whether the affiliate relationship is genuine. Final authenticity is determined by admin against the affiliate dashboard.

### Step 6 — Admin Packet

Once complete, send a single structured verification packet immediately to the admin destination containing:

- Telegram name/username/user ID
- BC.GAME user ID
- profile screenshot
- deposit screenshot(s)
- submission timestamp
- verification request ID
- Approve / Reject / Request Resubmission controls

### Step 7 — Manual Affiliate Check

Admin manually checks the BC.GAME affiliate dashboard and verifies whether the supplied BC.GAME ID/deposit corresponds to an attributed user.

### Step 8 — Decision

- `APPROVE`: persist approval and unlock main menu.
- `REJECT`: persist rejection and show a concise rejection state.
- `REQUEST RESUBMISSION`: preserve the reviewed packet as history and start a new evidence packet from the required step.

## Approved User Main Menu

The production user interface should remain minimal:

- `📊 BTC SIGNAL`
- `📈 MY RESULTS`
- `ℹ️ HOW IT WORKS`
- `🆘 SUPPORT`

Admins additionally receive `⚙️ ADMIN`.

## Signal Request Flow

1. Approved user selects BTC Signal.
2. Bot displays BTC/USDT + BC.GAME Up/Down context.
3. User taps `SCAN NOW`.
4. Backend verifies user status, service health, strategy status, and market-data freshness.
5. Signal intelligence returns `UP`, `DOWN`, `NO_TRADE`, or an `UNAVAILABLE` service state.
6. A valid directional signal includes planned entry, entry window, expiry, strategy version, and signal strength/calibrated confidence when available.
7. In `LIVE` presentation mode, every valid `UP` or `DOWN` signal must include a direct Telegram URL button labelled `🚀 Open BC.GAME Up/Down`, sourced from the single configurable `BCGAME_UPDOWN_URL` setting. Do not hardcode the destination URL inside handlers or strategy code.
8. In `PAPER` mode, directional results are validation-only: they must not use `ENTER NOW` language and must not include the BC.GAME execution button.
9. `NO_TRADE` responses must not include the BC.GAME trading button. They may include only safe actions such as `Scan Again`.
10. `UNAVAILABLE` means the service/provider cannot produce a valid strategy decision; it must not be recorded as strategy `NO_TRADE`.
11. Until entry, the signal may be cancelled if invalidation rules trigger.
12. At expiry, the outcome engine records the result.

## Frontend Design Rules

- Few screens, few images, few buttons.
- No button wall on `/start` for unapproved users.
- Use concise, polished Telegram messages.
- Visual identity may use a small number of branded assets, but correctness must never depend on images.
- Backend state is authoritative; Telegram message state is not.
- Direct trading-feature links must be configuration-driven so BC.GAME route changes can be repaired without changing signal logic.

## Admin Features

- Pending verification queue
- Approve/reject/resubmission
- Approved/suspended user management
- Broadcast composer and delivery summary
- System health summary
- Strategy status
- Kill switch visibility

## Broadcasts

Broadcasts are administrative communication, not automatic trading signals.

They must:

- target approved active users only;
- skip suspended/blocked users;
- use controlled batching/rate limiting;
- record success/failure counts;
- never block the real-time signal path.
