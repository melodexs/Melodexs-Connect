-- Read-only preflight for the three unique indexes in migration 002.
-- Run against the target staging database before applying migration 002.
-- This file contains SELECT statements only. NULL values excluded by each
-- partial index (and NULL key values that PostgreSQL treats as distinct) are
-- intentionally omitted.

-- uq_data_plans_provider_package
SELECT source, provider_code, provider_package_code, COUNT(*) AS row_count,
       ARRAY_AGG(id ORDER BY id) AS row_ids
FROM data_plans
WHERE source IS NOT NULL
  AND provider_code IS NOT NULL
  AND provider_package_code IS NOT NULL
GROUP BY source, provider_code, provider_package_code
HAVING COUNT(*) > 1
ORDER BY row_count DESC, source, provider_code, provider_package_code;

-- uq_transactions_reference
SELECT reference, COUNT(*) AS row_count, ARRAY_AGG(id ORDER BY id) AS row_ids
FROM transactions
WHERE reference IS NOT NULL
GROUP BY reference
HAVING COUNT(*) > 1
ORDER BY row_count DESC, reference;

-- uq_transactions_user_idempotency
-- idempotency_key IS NOT NULL is the migration's partial-index predicate.
-- user_id IS NOT NULL is additionally required for a duplicate to conflict:
-- PostgreSQL unique indexes allow multiple NULL values in a key column.
SELECT user_id, idempotency_key, COUNT(*) AS row_count,
       ARRAY_AGG(id ORDER BY id) AS row_ids
FROM transactions
WHERE idempotency_key IS NOT NULL
  AND user_id IS NOT NULL
GROUP BY user_id, idempotency_key
HAVING COUNT(*) > 1
ORDER BY row_count DESC, user_id, idempotency_key;
