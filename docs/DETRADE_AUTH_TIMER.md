# DeTrade Authorization and Timer Integration

This is the redacted implementation record from the authenticated BCGAME browser/CDP investigation. No credential value is included.

## Verified authorization flow

1. The already authenticated BCGAME page requests a temporary trading entry through `POST /api/platform-trading/tradingLogin/tradingLogin`. The observed request identifies the selected currency and balance type.
2. BCGAME returns a DeTrade entry target containing a one-time/temporary `accessCode`.
3. The DeTrade frontend sends that code to `POST https://api.detrade.com/api/tob/third-party/login/verify` as JSON containing `accessCode`.
4. DeTrade returns a temporary token plus account metadata including `accountType` and currency.
5. The normal web frontend keeps the token in its runtime state. It uses the token in DeTrade HTTP authorization and in the WebSocket connection/messages.

For the observed normal web path, the BCGAME session cookie is used only with BCGAME to obtain the temporary `accessCode`; it is not forwarded to the DeTrade WebSocket. The WebSocket carries no token-specific custom header: its token is in the query string and application payload, while ordinary `Origin` and `User-Agent` headers identify the web client. No persistent DeTrade user token was found in normal-web local/session storage. A separate native bridge contains storage/event hooks, but that was not the active browser path and is not used here.

The exact token lifetime was not exposed by the observed client and remains unverified. Auth failure codes `603` and `3100` are treated as expiry/re-authorization conditions. The official replacement behavior is to repeat the BCGAME `tradingLogin` step and DeTrade `login/verify` exchange; reusing the rejected token is unsafe.

## Verified WebSocket protocol

Endpoint:

```text
wss://websocket.detrade.com/ws
```

Query shape, with secret values redacted:

```text
token=<redacted>&device=web-pc&type=<accountType>&cid=<base64 browser user-agent>
```

Subscription object before compression:

```json
{
  "cmd": "/contest/BTC/USD/5/ticker/subscribe",
  "token": "<redacted>",
  "cid": "<base64 browser user-agent>",
  "reqId": "<unique UUID>"
}
```

The application heartbeat uses the same authenticated shape with `"cmd":"ping"` approximately every five seconds. Outbound messages and observed incoming binary frames use zlib-wrapped DEFLATE JSON. The implementation accepts that verified form first and has bounded fallbacks for plain JSON and raw DEFLATE.

The real authenticated ticker frames contain:

- `id`
- `status`
- `currentTime`
- `tradeCutoffTime`
- `priceStartTime`
- `priceEndTime`
- `startPrice`
- `endPrice`
- `previousRoundResult`

Unauthenticated subscription did not provide the real round/timer feed; authorization is required.

## Timer and status semantics

Five observed complete rounds showed that the visible betting countdown follows:

```text
remainingMilliseconds = priceStartTime - estimatedCurrentServerTime
estimatedCurrentServerTime = currentTime + local monotonic elapsed time
```

`priceStartTime`, rather than `tradeCutoffTime`, is therefore the authoritative visible countdown boundary for this integration. Each observed BTC/USD 5-second round had `priceEndTime - priceStartTime = 5000 ms`, and the round ID changed with the next round.

### Five-round validation evidence

Difference is `round(server remaining / 1000) - visible countdown digit`:

| Round ID | Samples | Avg signed | Avg absolute | Maximum | Price window |
|---|---:|---:|---:|---:|---:|
| `1352598948658185` | 65 | -0.14s | 0.97s | 7s boundary association anomaly | 5000ms |
| `1352599912528902` | 69 | -0.77s | 0.77s | 1s | 5000ms |
| `1352600908413967` | 73 | -0.70s | 0.70s | 1s | 5000ms |
| `1352601889946627` | 72 | -0.83s | 0.83s | 1s | 5000ms |
| `1352602872069133` | 75 | -0.63s | 0.63s | 1s | 5000ms |

Across 354 timer comparisons, the weighted signed difference was about `-0.62s` and weighted absolute difference about `0.77s`. Four rounds never differed from the one-second-resolution UI by more than one displayed second. The first round’s single seven-second maximum was a transient observer-to-UI association at the round boundary, not sustained drift.

Five primary rounds produced 290 normalized ticker updates (about 58 per round), with a mean interval near 515ms. `currentTime` changed on incoming frames; monotonic interpolation advanced smoothly between them. Frame-age spot checks were about 2–300ms. Precise one-way transport latency was not measurable because `currentTime` is application state time, not a dedicated synchronized send timestamp.

The verified/observed frontend status mapping used by the fail-closed implementation is:

| Code | Operational meaning | Actionable |
|---:|---|:---:|
| 1001 | betting/order window | yes, if fresh and early enough |
| 1002 | start payout stage | no |
| 1003 | trade cutoff | no |
| 1004 | payout stage | no |
| 1005 | finished | no |
| 1006 | ready to start | no |
| 1007 | cancelled | no |
| 1008 | observed transition; exact label not verified | no |
| other | unknown | no |

The observed transition sequence included `1001 → 1003 → 1002 → 1008 → 1004 → 1005 → 1006`. Only `1001` is ever actionable.

## Why unattended Render refresh is not implemented

The only verified token-minting input is an `accessCode` obtained from an authenticated BCGAME browser session. No official server-to-server client credential, refresh token, stable API key, documented OAuth grant, or safe Render-compatible BCGAME session bootstrap was observed. Implementing one would require storing or automating a BCGAME password/session cookie or guessing an undocumented contract, all of which violate the project’s credential and account-safety requirements.

The safe implementation is therefore:

- `EnvironmentDeTradeTokenProvider` reads a private Render secret at process start;
- known placeholders are rejected;
- credentials are never logged, serialized, persisted, sent to Telegram, or returned by health endpoints;
- auth failure clears the last frame and permanently invalidates that provider instance;
- HYBRID falls back to Scan Now while authorization is missing;
- AUTO fails closed;
- replacing `DETRADE_WS_TOKEN` in Render restarts the service and creates a fresh provider.

This is not automatic refresh, and the UI/health must not claim otherwise.

## Safe manual rotation for one read-only test

1. In the logged-in BCGAME Up/Down browser, open DevTools → Network → WS.
2. Select the live connection to `websocket.detrade.com/ws`.
3. In its request/query details, copy only the current `token` value. Treat it like a password; do not paste it into chat, source, logs, screenshots, or a local file. Confirm the accompanying non-secret `type` matches `DETRADE_CLIENT_TYPE` (the observed account used `1`).
4. In the existing Render web service, set the private environment value `DETRADE_WS_TOKEN` to that value and save. If the observed `type` differs, update `DETRADE_CLIENT_TYPE` to match. Do not add either token value to `render.yaml` as plaintext.
5. After the service restart, use the owner-only `/round_status` command. It prints normalized round state only.
6. If it reports expiration or no authorization, remove/replace the secret; do not retry the same rejected token.

No trade is placed by any of these steps or by the observer.
