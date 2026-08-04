-- Migration 003: conversations.client_session_id
-- Lets the backend upsert a conversation by the frontend's existing per-thread
-- UUID (ui/src/types.ts ChatSession.id) instead of minting a server-side id
-- and shuttling it back through the SSE protocol.
--
-- Apply on EC2 the same way as 001/002 (see their headers / CLAUDE.md
-- "DB role permissions gotcha") — as the postgres superuser via the
-- pg_hba.conf trust bypass:
--   psql -U postgres -d gaffer -f db/migrations/003_conversations_client_session_id.sql
--
-- No new grants needed: ALTER TABLE ADD COLUMN doesn't change table-level
-- privileges, and conversations is already scoped to gaffer_app only
-- (see 002_auth_tables.sql).

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS client_session_id TEXT UNIQUE;

COMMENT ON COLUMN conversations.client_session_id IS
    'The frontend''s stable per-thread id (crypto.randomUUID(), ui/src/types.ts). '
    'Not scoped to device_token/user_id at write time — see server/app_db.py '
    'upsert_conversation() for the accepted-gap note; must be fixed once a read '
    'path exists that could leak another session''s data.';
