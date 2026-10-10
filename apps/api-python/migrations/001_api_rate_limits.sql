-- Additive migration required by the Python API's PostgreSQL-backed limits.
-- Safe to apply to the existing MELODEXS CONNECT PostgreSQL database.
-- Rollback: DROP TABLE api_rate_limits; (only after reverting traffic to Node)
CREATE TABLE IF NOT EXISTS api_rate_limits (
    rate_key TEXT PRIMARY KEY,
    window_start BIGINT NOT NULL,
    request_count INTEGER NOT NULL
);
