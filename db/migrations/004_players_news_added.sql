-- Migration 004: players.news_added
-- fpl-context-mcp (>=0.7.0) documents players.news_added in the schema description
-- it hands Claude for query_historical_stats, so SQL referencing it must not fail.
-- etl_v2 upsert_players() writes it from FPL bootstrap's `news_added`.
--
-- Apply on EC2 the same way as 001-003 — as the postgres superuser via the
-- pg_hba.conf trust bypass (see CLAUDE.md "DB role permissions gotcha"):
--   psql -U postgres -d gaffer -f db/migrations/004_players_news_added.sql
--
-- No new grants needed: ADD COLUMN keeps existing table-level privileges.

ALTER TABLE players ADD COLUMN IF NOT EXISTS news_added TIMESTAMPTZ;

COMMENT ON COLUMN players.news_added IS
    'When FPL last changed this player''s news note (bootstrap-static news_added).';
