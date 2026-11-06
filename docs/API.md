# API reference

Base URL: `https://melodexs-connect-api.onrender.com`. All responses are JSON and
carry `success`. Authenticated routes take the session cookie, or
`Authorization: Bearer <session_token>` where the cookie is blocked.

## Session

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/register` | Creates an account and starts a session. |
| POST | `/api/login` | Returns the user plus `session_token`. |
| POST | `/api/logout` | Destroys the session (cookie and token). |
| GET | `/api/bootstrap` | Session owner + profile in one query; used by every page boot. |
| GET | `/api/session` | Compatibility probe; same payload shape. |
| POST | `/api/auth/google` | Verifies a Google ID token and signs the user in. |
| GET | `/api/auth/google/config` | Whether the Google button should render. |
| POST | `/api/forgot-password`, `/api/reset-password` | Email reset flow. |
| POST | `/api/profile-image` | 256x256 JPEG data URL, 300KB decoded cap. |

## Catalogue and data

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/data-plans` | `network` filter; mixed-source catalogue. |
| GET | `/api/data-categories` | Category list per network. |
| POST | `/api/purchase-data` | PIN, idempotency key, price revalidation. |
| POST | `/api/purchase-airtime` | Always fulfilled by WiseSub. |

## Billers

| Method | Path |
| --- | --- |
| GET | `/api/billers` |
| GET | `/api/billers/electricity`, `/api/billers/electricity/verify` |
| GET | `/api/billers/cable`, `POST /api/billers/cable/verify` |
| GET | `/api/billers/education` |
| POST | `/api/purchase-electricity`, `/api/purchase-cable`, `/api/purchase-education` |

Biller routes return 503 with "coming soon" while ISQUAREDATA is unconfigured or
disabled, so the UI can hide the form without a special case.

## Money

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/transactions/{user_id}` | Ownership enforced; supports type/status/q/limit/offset. |
| POST | `/api/fund-wallet`, `/api/fund-wallet/verify` | Paystack initialise and verify. The customer pays the full amount; a deposit fee is kept and only the rest is credited. Both responses report `fee` and `credit`/`credited`. |
| GET | `/api/deposit-fee` | Public. `{success, percent}`: the current deposit fee so the fund page can preview it. |
| POST | `/api/paystack/webhook` | Signed provider callback. |
| GET/POST/DELETE | `/api/favorites` | Saved recipients, 20 per user. |
| POST | `/api/purchase-pin/set`, `/change`, `/verify` | Four-digit purchase PIN. |

## Operations

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/status` | Health probe; also schedules the pending-purchase requery sweep. |
| GET | `/api/admin/*` | Admin only: catalogue, providers, users, transactions, reconciliation. |
| GET | `/api/admin/users/{id}` | Admin only, read-only. One customer: safe profile fields, a summary (pending, failed, purchases, `totalSpent`, `totalFunded`, `lastActivity`) and their transactions newest first. `?limit=` (1 to 500, default 100) and `?offset=`; `paging.hasMore` says whether older rows exist. Never returns password, PIN or reset-token fields. Descriptions are the full internal text, including supplier notes. 404 `Customer not found`, 403 for non-admins. |
| POST | `/api/webhooks/isquaredata` | HMAC-SHA512 over the raw body, `x-isquare-signature`. |

## Errors

`401` unauthenticated, `403` not allowed, `409` stale price or duplicate,
`429` rate limited, `503` capability not ready. Every error body is
`{"success": false, "message": "..."}`.
