-- 009_google_auth_nullable_phone.sql
-- Google Sign-In (PR #54). Accounts created through "Continue with
-- Google" have no phone number yet, so users.phone must accept NULL.
-- UNIQUE(phone) stays in place: PostgreSQL allows any number of NULLs
-- under a unique constraint, so real phone numbers keep their
-- one-account-per-number guarantee.
--
-- The API's startup schema guard is updated in the same PR
-- (EXPECTED_NOT_NULL["users"] no longer lists "phone").
--
-- Idempotent: the DO block only drops the constraint when it is present.
-- Applied to production (Neon) as an explicit owner-approved step.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'users'
          AND column_name = 'phone'
          AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE users ALTER COLUMN phone DROP NOT NULL;
    END IF;
END $$;
