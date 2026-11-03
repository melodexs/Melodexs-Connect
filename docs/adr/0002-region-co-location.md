# ADR 0002: run the database in the same region as the API

## Context

The API ran on Render in Oregon while PostgreSQL lived on Neon in London. Every
statement paid a transatlantic round trip. Measured on production, one statement
cost about 0.6s, so a login (three statements) took ~1.8s and a page boot two and
a half seconds. Neon's free plan does not allow raising the suspend timeout, and
keeping the compute awake continuously would consume almost the entire monthly
compute allowance.

## Decision

Create a PostgreSQL project in `us-west-2` and move the data there. Keep the
London project untouched as a rollback copy.

## How

The build sandbox cannot reach port 5432, so the copy ran over Neon's
SQL-over-HTTPS endpoint: recreate the schema from `app/database.py`, then read
and insert each table in batches and reset the serial sequences. Before switching,
the totals were compared (balances, transaction sums, plan counts, overrides,
providers). The switch itself is one environment variable plus a deploy.

## Consequences

* Login 1.8s → 0.67s; page boot 1.2s → 0.14s; catalogue reads 1.7s → 0.24s.
* Any future schema change must keep `schema_check.py` honest, because the
  application refuses to start on drift. Forgetting an index
  (`uq_users_reset_token_hash`) blocked two deploys until it was added.
* Region moves are now a documented, repeatable procedure rather than a migration
  nobody has done before.
