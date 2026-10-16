-- Migration 004: attach a generated-id default to data_plans.id.
--
-- The legacy production table was bulk-imported with explicit id values and
-- never received a serial default, unlike every other id column in the
-- schema. Both the reviewed Python requirements (app/schema_check.py
-- GENERATED_ID_COLUMNS) and the Node admin/sync INSERT paths, which omit the
-- id column, require data_plans.id to be database-generated. This migration is
-- purely additive and idempotent: existing rows keep their ids, and the
-- sequence is positioned so new inserts continue after the current maximum.
--
-- Guarded rerun safety: setval uses GREATEST(max(id) + 1, last_value) so a
-- re-run never moves the sequence backwards past values already handed out
-- (e.g. a rolled-back transaction that consumed a value).

CREATE SEQUENCE IF NOT EXISTS data_plans_id_seq OWNED BY data_plans.id;

ALTER TABLE data_plans
    ALTER COLUMN id SET DEFAULT nextval('data_plans_id_seq');

SELECT setval(
    'data_plans_id_seq',
    GREATEST(
        (SELECT COALESCE(MAX(id), 0) + 1 FROM data_plans),
        (SELECT last_value FROM data_plans_id_seq)
    ),
    false
);
