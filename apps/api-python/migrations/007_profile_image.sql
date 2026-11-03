-- 007_profile_image.sql
-- Adds the users.profile_image column for the profile picture feature
-- (PR #37). The API's init_schema() creates this column automatically for
-- SQLite (tests), but production PostgreSQL only takes explicit reviewed
-- migrations — the column was missing in production, which made every
-- user read (login, register, session, profile) fail with 500.
--
-- Applied to production (Neon, project frosty-meadow-70077475) on
-- 2026-10-22 via SQL-over-HTTPS. Idempotent.

ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_image TEXT;
