-- 008_favorite_recipients.sql
-- Creates the favorite_recipients table for saved recipient numbers
-- (PR #36). Same production gap as 007: init_schema() covers SQLite
-- (tests) only; production PostgreSQL takes explicit migrations.
--
-- Applied to production (Neon, project frosty-meadow-70077475) on
-- 2026-10-22 via SQL-over-HTTPS. Idempotent.

CREATE TABLE IF NOT EXISTS favorite_recipients (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    label TEXT,
    phone TEXT NOT NULL,
    network TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
