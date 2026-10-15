-- Additive PostgreSQL invariant: a reset-token hash can belong to at most
-- one user. Run diagnostics/reset_token_unique_preflight.sql first; do not
-- remove or choose among duplicate rows automatically.
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_reset_token_hash
    ON users(reset_token_hash)
    WHERE reset_token_hash IS NOT NULL;
