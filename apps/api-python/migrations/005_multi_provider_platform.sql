-- Multi-provider data fulfillment platform (additive, backward compatible).
--
-- Adds:
--  * providers: registry rows for fulfillment providers. WiseSub ships
--    enabled (it is the active production provider); every additional
--    provider ships DISABLED until an admin enables it after credentials
--    are configured and verified.
--  * transactions.provider: the provider that fulfilled (or is holding) a
--    purchase. NULL for all pre-existing rows means WiseSub (legacy rows
--    are never rewritten).
--
-- Rollback:
--   ALTER TABLE transactions DROP COLUMN IF EXISTS provider;
--   DROP TABLE IF EXISTS providers;
-- The application treats a missing providers table as " WiseSub only",
-- so a rollback restores the previous single-provider behavior safely.

CREATE TABLE IF NOT EXISTS providers (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    status TEXT,
    last_check_at TIMESTAMP,
    last_check_detail TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS provider TEXT;

INSERT INTO providers (slug, name, enabled)
VALUES ('wisesub', 'WiseSub', 1)
ON CONFLICT (slug) DO NOTHING;

-- Additional providers are known but deliberately disabled:
INSERT INTO providers (slug, name, enabled)
VALUES ('meledata', 'MELE DATA', 0)
ON CONFLICT (slug) DO NOTHING;
INSERT INTO providers (slug, name, enabled)
VALUES ('rizpay', 'RizPay', 0)
ON CONFLICT (slug) DO NOTHING;

-- WiseSub must stay enabled: it is the primary fulfillment provider while
-- multi-provider routing is disabled.
UPDATE providers SET enabled = 1 WHERE slug = 'wisesub';
