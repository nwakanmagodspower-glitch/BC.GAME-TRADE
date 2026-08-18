# BC.GAME TRADE

Production-focused Telegram signal platform for **BC.GAME BTC/USDT Up/Down**.

## V1 Scope

- One product: **BC.GAME Up/Down**
- One market: **BTC/USDT**
- On-demand scans only
- Outputs: `UP`, `DOWN`, or `NO_TRADE`
- Exact planned entry time and expiry time
- Manual BC.GAME execution by the user
- Manual affiliate verification before access
- Render-first deployment
- Telegram as the user/admin interface
- PostgreSQL as persistent memory

## Non-goals for V1

- No automatic BC.GAME trade execution
- No Martingale or recovery doubling
- No guaranteed-win claims
- No additional coins or BC.GAME trading products without an explicit milestone
- No scheduled public signal broadcasting

## Core Flow

1. User starts bot.
2. Bot starts guided onboarding; no main-menu buttons are shown yet.
3. User is guided to registration.
4. User is guided to deposit.
5. User submits BC.GAME profile/user ID evidence and deposit screenshot(s).
6. Submission is sent immediately to admin.
7. Admin manually checks the affiliate dashboard and approves/rejects.
8. Approved user is remembered in PostgreSQL.
9. Main menu becomes available.
10. User requests a BTC signal on demand.
11. Intelligence engine returns `UP`, `DOWN`, or `NO_TRADE`.
12. Valid signals include exact entry and expiry times.
13. Outcomes are recorded automatically for strategy evaluation.

## Architecture Principles

- Telegram is an interface, not the strategy engine.
- Market-data providers are replaceable adapters.
- BC.GAME-specific integrations are isolated behind a BC.GAME adapter.
- Strategy versions are immutable and measurable.
- Stale or unhealthy data fails closed: no signal is better than a bad signal.
- Frontend stays simple and visual; backend carries state, validation, auditability, and reliability.

See `AGENTS.md` and the documents under `docs/` before writing production code.