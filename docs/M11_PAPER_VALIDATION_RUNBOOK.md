# M11 — Paper Production Validation Runbook

This runbook is subordinate to `AGENTS.md`, `ARCHITECTURE.md`, `DEPLOYMENT.md`, `STRATEGY_RULES.md`, `MILESTONES.md`, and `RENDER_DEPLOY_CHECKLIST.md`.

## Purpose

Demonstrate technical correctness under real Render runtime conditions using live BTC/USDT market data while remaining in PAPER mode. This milestone does not authorize automated BC.GAME trading or LIVE signal presentation.

## Required starting state

- Render web, worker, and PostgreSQL are healthy.
- `SIGNAL_MODE=PAPER`.
- `SIGNALS_ENABLED=false` at deployment default.
- `BROADCASTS_ENABLED=false`.
- V1 identity is `BTCUSDT` + `BC_UPDOWN` + 300 seconds.
- Telegram webhook is verified.
- Onboarding and approval gates have passed smoke testing.

## Controlled paper-test procedure

1. Owner opens `/admin` and verifies PAPER mode and fresh market data.
2. Keep public/beta users out of the test cohort.
3. Enable only the runtime signal gate for the approved test account(s). Do not change `SIGNAL_MODE` to LIVE.
4. Request on-demand BTC scans at varied times and market conditions.
5. For each directional signal, allow the worker to process entry timing, cancellation, activation, and settlement without manual database edits.
6. Record any Telegram delivery delay, missing notification, stale-data rejection, cancellation, or settlement delay.
7. Periodically open `/admin` → `Paper Validation` and review blockers.
8. Run `python scripts/paper_validation_report.py` against the production database when a larger sample has accumulated.
9. Disable the runtime signal gate immediately after each controlled test session if active testing is not continuing.

## Technical evidence required

- real live BTC market snapshots are fresh at scan time;
- directional candidates activate only inside the configured entry window;
- invalid or stale candidates cancel rather than activate;
- active signals settle automatically;
- entry and expiry reference prices are persisted;
- lifecycle Telegram notifications are delivered or failures are auditable;
- no duplicate lifecycle processing is observed;
- strategy identity remains unchanged;
- the owner can disable signals without disabling onboarding/support.

## Pass conditions

M11 is technically passable only when the paper-validation service reports no blockers and repeated runtime observation shows no material lifecycle defect.

A pass does **not** mean the strategy is profitable and does not prove exact BC.GAME settlement matching. Strategy performance and BC.GAME reference-price parity remain separate evidence questions.

## Immediate stop conditions

Disable the runtime signal gate and investigate if any of these occur:

- stale data produces a directional signal;
- activation occurs outside the allowed entry window;
- duplicate ENTER NOW or settlement notifications are repeatedly emitted;
- worker restart causes duplicate outcome mutation;
- a settled signal lacks entry or expiry reference price;
- strategy pair/product/expiry/version changes unexpectedly;
- unapproved users can request scans;
- PAPER mode is changed to LIVE accidentally.

## M12 gate

Do not begin Controlled Live Beta until M11 technical validation is complete and the owner explicitly decides to proceed. M12 remains manual execution only.
