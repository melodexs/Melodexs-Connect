# Environment compatibility

| Variable | Node use | Python use | Required in production |
|---|---|---|---|
| `PORT` | Express listen port | Uvicorn port | Yes |
| `NODE_ENV` | Production checks/cookies/reset email | Production checks/cookies/reset email | Yes |
| `DATABASE_URL` | PostgreSQL pool/session store | SQLAlchemy PostgreSQL engine | Yes |
| `SESSION_SECRET` | Express session signing | Python session signing | Yes; 32+ characters |
| `PAYSTACK_SECRET_KEY` | Paystack API and webhook HMAC | Paystack API and webhook HMAC | Yes for wallet funding |
| `CHEAPDATA_PUBLIC_URL` | Reset/payment callback and CORS | Reset/payment callback and CORS | Yes |
| `WISESUB_BASE_URL` | WiseSub base URL | WiseSub base URL | Yes for purchases |
| `WISESUB_API_KEY` | WiseSub bearer header | WiseSub bearer header | Yes for purchases |
| `WISESUB_API_SECRET` | WiseSub secret header | WiseSub secret header | Yes for purchases |
| `WISESUB_ENVIRONMENT` | Test/live provider mode | Test/live provider mode | Yes |
| `CHEAPDATA_MARKUP_PERCENT` | Used by plan-sync tooling | Configured but not applied in runtime purchase logic | Yes for matching sync pricing |
| `BREVO_API_KEY` | Brevo `api-key` header | Brevo `api-key` header | Yes for production reset email |
| `BREVO_FROM_EMAIL` | Brevo sender | Brevo sender | Yes for production reset email |
| `BREVO_FROM_NAME` | Brevo sender name | Brevo sender name | No; default exists |
| `DB_PATH` | Legacy SQLite scripts | Not used by Python runtime | No |

No secret values are included in this table or committed files.

The Python rate limiter additionally creates `api_rate_limits` in the same database. It is additive and must be included in PostgreSQL schema validation; no production table is dropped or recreated automatically.
