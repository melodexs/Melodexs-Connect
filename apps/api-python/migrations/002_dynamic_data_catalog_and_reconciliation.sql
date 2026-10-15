-- Reviewed additive migration for PostgreSQL staging. Do not apply to
-- production until the current schema and any duplicate provider package or
-- transaction references have been inspected and staging validated.
ALTER TABLE data_plans
    ADD COLUMN IF NOT EXISTS provider_available INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS selling_price_override DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS category TEXT,
    ADD COLUMN IF NOT EXISTS provider_category TEXT,
    ADD COLUMN IF NOT EXISTS sync_error TEXT;

-- Existing values may have been explicitly set by administrators in the old
-- Node admin UI, which had no override flag. Preserve them as fixed overrides
-- until an admin explicitly clears the override in the new dashboard.
UPDATE data_plans
SET selling_price_override = selling_price
WHERE LOWER(TRIM(COALESCE(source, ''))) = 'wisesub'
  AND selling_price_override IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_data_plans_provider_package
    ON data_plans(source, provider_code, provider_package_code)
    WHERE source IS NOT NULL AND provider_code IS NOT NULL AND provider_package_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS data_plan_sync_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    outcome TEXT NOT NULL,
    added INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    unavailable INTEGER NOT NULL DEFAULT 0,
    errors TEXT
);

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS provider_reference TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_reference
    ON transactions(reference) WHERE reference IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_user_idempotency
    ON transactions(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
