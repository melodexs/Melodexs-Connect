# PostgreSQL migration staging procedure

Use a dedicated PostgreSQL staging database or an isolated copy restored from
a backup. Never configure a production connection string as a test target.
The test gate requires a separate `POSTGRES_TEST_DATABASE_URL`, exact expected
host, database, and username values, plus `POSTGRES_TEST_DATABASE_VERIFIED=YES`.
The database name is not treated as proof of safety. No combination of URL
checks and manual confirmation can mathematically prove that a database is
disposable; an operator must independently verify the target and its ownership
before opting in.

1. Restore or provision the isolated database and take a disposable snapshot.
   Independently verify its host, database name, owner, and that it contains no
   production data. Set the required variables `POSTGRES_TEST_DATABASE_URL`,
   `POSTGRES_TEST_EXPECTED_HOST`, `POSTGRES_TEST_EXPECTED_DATABASE`,
   `POSTGRES_TEST_EXPECTED_USERNAME`, and `POSTGRES_TEST_DATABASE_VERIFIED=YES`.
   Supply the URL through a protected environment or secret manager; do not put
   credentials in documentation or shell history. The URL must use
   `sslmode=verify-full`. Set `NODE_ENV=production`,
   `WISESUB_ENVIRONMENT=live`, and the repository's approved WiseSub endpoint
   in the staging process configuration. Startup validates these values, but
   the documented migration and PostgreSQL concurrency tests do not send
   WiseSub requests.
2. Before migration 002, run the read-only duplicate diagnostics in
   `diagnostics/unique_index_preflight.sql`. Review all returned row IDs.
   Any returned group conflicts with a migration index and must be resolved
   deliberately in staging before proceeding. The SQL does not alter data.
3. Before migration 003, run
   `diagnostics/reset_token_unique_preflight.sql`. It reports every group
   whose non-null reset-token hash is duplicated. Resolve returned groups
   deliberately; do not delete rows or select a winning account automatically.
   The SQL does not alter data.
4. Apply the reviewed migrations manually to staging, in order. Do not run
   them via application startup. Keep a record of the exact database and
   migration versions used.
5. Run the read-only schema checker using the staging-only configuration:

   ```sh
   PYTHONPATH=apps/api-python python -m app.schema_check
   ```

   Confirm `database_dialect` is `postgresql`, `postgresql_verified` is true,
   and each table has no missing columns, constraints, indexes, incompatible
   types/defaults, unexpected nullable columns, incompatible indexes, or
   missing generated-ID defaults.
6. Only after schema validation, and after independently rechecking that the
   configured target is disposable, a separately authorized operator may run
   the PostgreSQL concurrency suite. The gate compares parsed URL host,
   database, and username against the exact expected values, rejects a match
   with `DATABASE_URL` from the environment or repository `.env`, and checks
   the connected PostgreSQL database/user and TLS-verified hostname before
   application startup or test execution. Invalid opt-in configuration fails
   before the application database engine is imported. The suite writes test
   records, so the target must remain disposable.

   ```sh
   RUN_POSTGRES_INTEGRATION=1 \
   POSTGRES_TEST_DATABASE_VERIFIED=YES \
   POSTGRES_TEST_DATABASE_URL="$DISPOSABLE_TEST_POSTGRES_URL" \
   POSTGRES_TEST_EXPECTED_HOST="$EXACT_TEST_HOST" \
   POSTGRES_TEST_EXPECTED_DATABASE="$EXACT_TEST_DATABASE" \
   POSTGRES_TEST_EXPECTED_USERNAME="$EXACT_TEST_USERNAME" \
     .venv/bin/python -m pytest -q apps/api-python/tests/test_postgres_concurrency.py
   ```

   Replace placeholders only in the protected test environment. Never use
   production. This procedure is documentation only; migration and
   integration commands are not run as part of ordinary local verification.
   PostgreSQL behavior remains unverified until this separately authorized run
   completes successfully.
