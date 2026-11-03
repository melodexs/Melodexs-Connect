# Database

Production is PostgreSQL on Neon (`us-west-2`, same region as the API). Tests run
on a throwaway SQLite file per run.

## Tables

| Table | Purpose |
| --- | --- |
| `users` | Accounts, wallet balance, purchase PIN, reset token, profile picture. |
| `sessions` | Server-side sessions: `sid`, `sess` (JSON `{"userId": n}`), `expire` (epoch ms). |
| `data_plans` | One row per purchasable bundle, including price overrides and provider availability. |
| `data_plan_sync_runs` | Audit of each catalogue synchronisation. |
| `transactions` | Every wallet movement, purchase or funding, with provider references. |
| `favorite_recipients` | Saved numbers, at most 20 per user. |
| `providers` | Runtime enable/disable state per supplier, independent of the code registry. |
| `api_rate_limits` | Fixed-window counters keyed by route and client. |

## Invariants worth protecting

* `users.balance` only moves through a single conditional `UPDATE` that decrements
  the wallet and inserts the transaction together, so a double submit cannot
  spend twice.
* `transactions.reference` and `(user_id, idempotency_key)` are uniquely indexed;
  a retried request returns the original row instead of charging again.
* `data_plans` keeps `selling_price` (what the customer pays) separate from
  `provider_cost`, and an override always wins over the computed price.

## Migrations

Production schema changes are explicit, reviewed SQL. The application never
creates or alters tables against PostgreSQL: `startup()` runs
`schema_incompatibilities(inspect_schema())` and refuses to boot on any drift.
That guard is why a hand-built database missing `uq_users_reset_token_hash`
cannot serve traffic.

SQLite (tests and local runs only) is created with `init_schema()`.

## Copying data between regions

Postgres port 5432 is not reachable from the build sandbox, so cross-region copies
run through Neon's SQL-over-HTTPS endpoint: read each table, insert in batches,
then `setval` every serial sequence. Verify totals (balances, transaction sums,
plan counts, overrides) before switching `DATABASE_URL`, and keep the previous
project intact until the new one has served real traffic.
