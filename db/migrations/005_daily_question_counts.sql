-- Migration 005: daily_question_counts — free-tier allowance for /fpl/ask
-- One row per (usage_key, UTC day). usage_key is 'user:<users.id>' for a signed-in
-- user, otherwise 'ip:<salted hash of the client IP>' — no raw IPs are stored.
-- Kept in Postgres rather than the in-memory rate limiter because the app runs
-- 2 uvicorn workers (each would keep its own count) and restarts on every deploy.
--
-- Apply on EC2 the same way as 001-004 — as the postgres superuser via the
-- pg_hba.conf trust bypass (see CLAUDE.md "DB role permissions gotcha"):
--   psql -U postgres -d gaffer -f db/migrations/005_daily_question_counts.sql
--
-- Until it is applied the app fails open: the count query errors, the error is
-- logged as daily_limit.check_failed, and the question is answered as before.

CREATE TABLE IF NOT EXISTS daily_question_counts (
    usage_key       TEXT NOT NULL,
    day             DATE NOT NULL,
    question_count  INT  NOT NULL DEFAULT 0,
    PRIMARY KEY (usage_key, day)
);

-- Created as postgres, so it inherits the default gaffer_readonly / gaffer_etl
-- grants (see 002_auth_tables.sql) — revoke them; only the app touches this table.
REVOKE ALL ON daily_question_counts FROM gaffer_readonly;
REVOKE ALL ON daily_question_counts FROM gaffer_etl;

GRANT SELECT, INSERT, UPDATE, DELETE ON daily_question_counts TO gaffer_app;
