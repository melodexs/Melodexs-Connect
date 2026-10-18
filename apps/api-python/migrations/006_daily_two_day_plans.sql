-- Migration 006: re-bucket 2-day plans from Weekly Plans to Daily Plans.
--
-- Background: app/categorization.py previously placed 2-day validity packs
-- in "Weekly Plans". Product review (Oct 2026) decided 1-2 day packs are
-- daily-budget buys and must appear under "Daily Plans"; Weekly now covers
-- 3-7 days. The Python rule is fixed in the same release; this migration
-- corrects rows already stored by past syncs so customers see the same
-- bucketing immediately instead of waiting for the next provider sync
-- (a sync only updates a row's category when the row has no admin-set
-- category, so waiting would leave stale Weekly labels indefinitely).
--
-- Scope guard: only rows explicitly categorized "Weekly Plans" whose stored
-- validity is exactly "2 Days" are moved. Weekly rows with 3-7 day
-- validity, admin-set categories on other rows, and legacy/uncategorized
-- rows are untouched. Idempotent: re-running moves nothing new.

UPDATE data_plans
SET category = 'Daily Plans',
    updated_at = NOW()
WHERE category = 'Weekly Plans'
  AND LOWER(TRIM(COALESCE(validity, ''))) = '2 days';
