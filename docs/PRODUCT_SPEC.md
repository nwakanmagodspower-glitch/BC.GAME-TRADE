# Product Specification

## Product Definition

BC.GAME TRADE is an on-demand Telegram signal assistant specialized for **BTC/USD 5-second Up/Down rounds on BC.GAME**.

Observed game flow:

1. BC.GAME opens an order countdown.
2. Users choose UP or DOWN before the countdown ends.
3. At countdown end / first flag, BC.GAME records the **Start Rate**.
4. The selected contract runs for **5 seconds**.
5. At the second flag, BC.GAME records the **End Rate**.
6. `End Rate > Start Rate` => UP wins; otherwise DOWN wins according to the supplied How to Trade instructions.

V1 targets the visible `5s $1-50` band first. `$50-100` and `$100-200` remain out of scope until measured and approved.

## Important Data Boundary

BC.GAME displays BTC/USD. The initial external analysis feed may be Binance BTCUSDT because it provides high-quality tick/trade data, but it is **not BC.GAME settlement truth**. LIVE claims require round/start/end-rate synchronization against BC.GAME itself.

## User States

`NEW`, onboarding states, `PENDING_REVIEW`, `APPROVED`, `REJECTED`, `RESUBMISSION_REQUIRED`, `SUSPENDED`, `BLOCKED`.

## Guided Onboarding

Before approval there is no normal menu. Flow:

1. Registration guidance using configured affiliate link.
2. Deposit guidance.
3. Text BC.GAME User ID.
4. Profile screenshot showing User ID.
5. One or more deposit screenshots.
6. Backend completeness validation.
7. Complete packet sent immediately to the bot owner's private Telegram chat.
8. Owner checks BC.GAME affiliate dashboard manually.
9. Approve / Reject / Request Resubmission.
10. Resubmission preserves old evidence history.
11. Only APPROVED users receive the normal menu.

## Approved User Main Menu

- `⚡ BTC 5s SIGNAL`
- `📈 MY RESULTS`
- `ℹ️ HOW IT WORKS`
- `🆘 SUPPORT`

Owner additionally receives admin controls.

## Signal UX Contract

1. Approved user selects `⚡ BTC 5s SIGNAL`.
2. Bot shows concise context: `BTC/USD • BC.GAME Up/Down • 5s • $1-50`.
3. Bot explains that the signal targets the price movement **from BC.GAME Start Rate to End Rate**, not the pre-start countdown movement.
4. User taps `🔍 SCAN NEXT ROUND`.
5. Backend checks access, signal kill switch, worker heartbeat, market-data freshness, strategy health, round synchronization, and remaining human-action lead time.
6. Engine returns `UP`, `DOWN`, `NO_TRADE`, or `UNAVAILABLE`.
7. `UP/DOWN` is actionable only if the system knows which BC.GAME round/order window it refers to and enough time remains to act.
8. PAPER mode never displays `ENTER NOW` or the execution button.
9. LIVE mode may show `🚀 Open BC.GAME Up/Down` only when round synchronization is trustworthy and the order window is still actionable.
10. `NO_TRADE` means the round is deliberately skipped.
11. `UNAVAILABLE` means data/round synchronization/service health prevents a valid decision; it is not strategy `NO_TRADE`.

## Signal Card — LIVE Target

A valid future LIVE card should contain only information a human needs quickly:

```text
⚡ BTC/USD — 5s UP/DOWN

🟢 UP   or   🔴 DOWN
Round: next synchronized BC.GAME round
Order window remaining: <known countdown>
Contract: 5s • $1-50
Quality: <calibrated label>

Place the order before BC.GAME countdown reaches 0.
```

Buttons:

- `🚀 Open BC.GAME Up/Down`
- `🔄 Scan Next Round`
- `⬅️ Main Menu`

Do not overload the card with indicators. Backend evidence belongs in logs/research records.

## Signal Intelligence Scope

### Context features

- short trend / regime
- volatility
- support/resistance proximity
- short momentum

### Primary 5-second features

- tick price velocity and acceleration
- aggressive buy/sell trade-flow imbalance
- very-short-window volume imbalance
- spread and liquidity quality
- order-book imbalance / microprice when available
- cross-exchange agreement when validated

A slow indicator by itself must never trigger a 5-second signal.

## BC.GAME Round Research Fields

When a reliable structured source is discovered, collect:

- round identifier
- order-window start/end timestamps
- Start Rate timestamp/value
- End Rate timestamp/value
- actual UP/DOWN result
- UP/DOWN payout percentage
- UP/DOWN pool amounts
- UP/DOWN player counts
- selected 5-second stake band

Pool/player information is research data, not directional evidence until validated statistically.

## Outcome Contract

Primary truth for product validation is BC.GAME Start Rate versus End Rate. External exchange prices may be stored as reference diagnostics but must not overwrite BC.GAME-labelled outcomes.

Until a reliable BC.GAME round/result source is integrated, PAPER results must explicitly say they are external-reference results.

## Frontend Rules

- Few screens, few images, few buttons.
- No menu wall before approval.
- The signal path must be fast enough for a short countdown.
- Avoid unnecessary images during a time-sensitive signal.
- Backend state is authoritative.
- BC.GAME links are configuration-driven.
- Never encourage Martingale, loss recovery, guaranteed profit, or forced round participation.

## Admin Features

- Verification decisions in owner's private bot chat
- Approved/suspended user management
- Signals on/off
- PAPER/LIVE status
- Worker/data/round-sync health
- Strategy version
- Broadcast composer and summary
- Database/retention health

## Broadcasts

Broadcasts target approved active users only, are rate-limited, record delivery summaries, and must never block the real-time scan path.
