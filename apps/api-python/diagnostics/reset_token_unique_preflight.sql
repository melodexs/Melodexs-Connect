-- Read-only aggregate preflight for migration 003. Returns only the number of
-- duplicate hash groups and the total rows in those groups; no hashes or IDs.
WITH duplicate_groups AS (
    SELECT COUNT(*) AS row_count
    FROM users
    WHERE reset_token_hash IS NOT NULL
    GROUP BY reset_token_hash
    HAVING COUNT(*) > 1
)
SELECT COUNT(*) AS duplicate_hash_groups,
       COALESCE(SUM(row_count), 0) AS rows_in_duplicate_groups
FROM duplicate_groups;
