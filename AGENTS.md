# AGENTS.md

These rules govern every coding agent, developer, automation, and deployment change in this repository.

## Product Boundary

V1 is intentionally narrow:

- BC.GAME product: **Up/Down**
- Market: **BTC/USDT**
- User action: **on-demand scan**
- Outputs: `UP`, `DOWN`, `NO_TRADE`
- Manual user execution on BC.GAME
- Manual affiliate verification before access

Do not expand scope unless an explicit milestone authorizes it.

## Mandatory Rules

Every implementation MUST:

- preserve BTC/USDT Up/Down as V1 scope;
- keep Telegram separate from signal intelligence;
- keep market-data providers replaceable;
- keep BC.GAME-specific logic behind an adapter;
- version every production strategy;
- record every generated signal and final result;
- use exact timestamps for creation, planned entry, entry window, and expiry;
- fail closed when market data is stale or unhealthy;
- preserve `NO_TRADE` as a first-class outcome;
- keep secrets out of GitHub;
- use database migrations for schema changes;
- keep Render compatibility;
- preserve paper/live-signal mode separation;
- preserve owner/admin kill switches;
- make onboarding state persistent so approved users remain approved after restarts;
- keep the Telegram UI minimal while backend validation and audit trails remain complete.

## Prohibited Changes

Do NOT:

- add coins or BC.GAME products without approval;
- implement automatic BC.GAME trade placement in V1;
- add Martingale, loss chasing, or forced recovery logic;
- fabricate confidence scores;
- claim guaranteed accuracy or guaranteed profit;
- bypass manual access approval;
- expose the main menu before onboarding/approval is complete;
- hardcode admin IDs throughout business logic;
- silently change thresholds, weights, expiry rules, or strategy parameters;
- overwrite historical strategy results after a new version is deployed;
- allow stale market data to produce signals;
- allow broadcasts to block signal requests;
- store unnecessary raw market streams indefinitely in the main PostgreSQL database.

## Verification Funnel Contract

Before approval, the bot must behave as a guided workflow, not a menu-driven bot.

Required onboarding sequence:

1. Registration guidance.
2. Deposit guidance.
3. Request BC.GAME profile/user ID evidence.
4. Request deposit screenshot(s).
5. Validate that required evidence is present.
6. Forward the complete verification packet immediately to admin.
7. Persist status as `PENDING_REVIEW`.
8. Admin manually checks the affiliate dashboard.
9. Admin chooses approve, reject, or request resubmission.
10. Only `APPROVED` users receive the normal bot menu.

The backend must associate all submitted evidence with the correct Telegram user and verification request. Duplicate submissions must be idempotent or explicitly versioned.

## Signal Safety Contract

A signal may be returned only when:

- market data passes freshness/health checks;
- the configured strategy is active;
- the requested product and pair match supported scope;
- quality thresholds are met;
- planned entry is still actionable;
- the signal has not been invalidated before entry.

Otherwise return `NO_TRADE` or service-unavailable status.

## Deployment Gates

No production deployment may bypass the milestone gates in `docs/MILESTONES.md` and `docs/DEPLOYMENT.md`.

## Source of Truth

When instructions conflict, use this precedence:

1. Explicit current owner instruction.
2. `AGENTS.md`.
3. `docs/PRODUCT_SPEC.md`.
4. `docs/ARCHITECTURE.md`.
5. Other repository documentation.
6. Existing implementation details.

If implementation conflicts with the documented product boundary, fix the implementation rather than silently changing the product definition.