# AGENTS.md

These rules govern every coding agent, developer, automation, and deployment change in this repository.

## Product Boundary

V1 is intentionally narrow and is based on the observed BC.GAME Up/Down interface and its published How to Trade flow:

- BC.GAME product: **Up/Down**
- Game display market: **BTC/USD**
- External analysis market: **BTCUSDT initially**, treated only as a reference/analysis feed until BC.GAME price-source matching is validated
- Contract duration: **5 seconds**
- Initial stake band: **5s $1-50**; other stake bands are research-only until explicitly approved
- User action: **on-demand scan for an actionable upcoming BC.GAME round**
- Outputs: `UP`, `DOWN`, `NO_TRADE`, `UNAVAILABLE`
- Manual user execution on BC.GAME only
- Manual affiliate verification before access

The BC.GAME game contract is round-based: users place orders during a countdown; when the countdown ends BC.GAME records the Start Rate at the first flag; after the selected 5-second period BC.GAME records the End Rate at the second flag. End > Start means UP wins; otherwise DOWN wins according to the supplied game instructions.

Do not expand scope unless an explicit milestone authorizes it.

## Mandatory Rules

Every implementation MUST:

- preserve BTC/USD 5-second BC.GAME Up/Down as V1 product scope;
- treat BTCUSDT/Binance as an analysis feed, not BC.GAME settlement truth;
- keep Telegram separate from signal intelligence;
- keep market-data providers replaceable;
- keep BC.GAME-specific round/product logic behind an adapter;
- version every production strategy;
- record every generated directional/no-trade decision and final result when a trustworthy result source exists;
- use exact timestamps for scan time, BC.GAME order-window timing, Start Rate time, and End Rate time when available;
- require reliable round synchronization before presenting a LIVE actionable signal;
- fail closed when market data, round timing, or worker health is stale/unhealthy;
- preserve `NO_TRADE` as a first-class outcome;
- keep secrets out of GitHub;
- use database migrations for schema changes;
- keep Render compatibility;
- preserve PAPER/LIVE separation and owner kill switches;
- keep onboarding state persistent;
- keep Telegram UI minimal while backend validation and audit trails remain complete;
- keep latency visible: a signal that cannot reach a human with enough time to act before the BC.GAME order window closes is not actionable.

## Prohibited Changes

Do NOT:

- add coins, durations, or BC.GAME products without approval;
- implement automatic BC.GAME trade placement in V1;
- add Martingale, loss chasing, or forced recovery logic;
- fabricate confidence scores;
- claim guaranteed accuracy or guaranteed profit;
- treat leaderboard win rates or crowd/pool direction as predictive without measured evidence;
- treat Binance settlement as identical to BC.GAME settlement without validation;
- bypass manual access approval;
- expose the main menu before onboarding/approval is complete;
- hardcode admin IDs throughout business logic;
- silently change thresholds, feature weights, duration rules, or timing rules;
- overwrite historical strategy results after a new version is deployed;
- allow stale market data or stale round timing to produce actionable signals;
- allow broadcasts to block signal requests;
- store unnecessary raw market streams indefinitely in PostgreSQL;
- re-enable GitHub Actions while the owner has asked that Actions not be used.

## Verification Funnel Contract

Before approval, the bot is a guided workflow, not a menu-driven bot:

1. Registration guidance.
2. Deposit guidance.
3. BC.GAME User ID.
4. Profile screenshot.
5. Deposit screenshot(s).
6. Validate completeness.
7. Forward the complete packet directly to the bot owner's private Telegram chat.
8. Persist `PENDING_REVIEW`.
9. Owner checks affiliate dashboard manually.
10. Owner chooses approve, reject, or request resubmission.
11. Only `APPROVED` users receive the normal bot menu.

Resubmission must preserve the previous reviewed packet as history.

## Signal Safety Contract

An actionable directional signal may be returned only when:

- approved user access is valid;
- signals are enabled;
- dedicated worker health is fresh;
- external market data is fresh;
- the configured strategy is active;
- the BC.GAME product/duration/stake band match supported V1 scope;
- BC.GAME round/order-window synchronization is trustworthy;
- enough human-action lead time remains;
- quality thresholds are met;
- the signal has not been invalidated before the relevant round locks.

Otherwise return `NO_TRADE` or `UNAVAILABLE`. In PAPER/research mode, the system may evaluate reference outcomes without presenting an execution instruction.

## Source of Truth

When instructions conflict, use this precedence:

1. Explicit current owner instruction.
2. `AGENTS.md`.
3. `docs/PRODUCT_SPEC.md`.
4. `docs/ARCHITECTURE.md`.
5. `docs/STRATEGY_RULES.md`.
6. Other repository documentation.
7. Existing implementation details.
