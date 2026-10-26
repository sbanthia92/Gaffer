-- Migration 006: users.fpl_team_id
-- Lets a signed-in account keep its FPL team ID server-side so it follows the user to
-- other devices (it was localStorage-only). Written by PUT /fpl/team-id, read by /auth/me.
--
-- Apply on EC2 the same way as 001-005 — as the postgres superuser via the
-- pg_hba.conf trust bypass (see CLAUDE.md "DB role permissions gotcha"):
--   psql -U postgres -d gaffer -f db/migrations/006_users_fpl_team_id.sql
--
-- No new grants needed: ADD COLUMN keeps gaffer_app's existing table-level privileges.
-- Until it is applied /auth/me omits the field (the read fails soft) and saving returns 500.

ALTER TABLE users ADD COLUMN IF NOT EXISTS fpl_team_id INT;
