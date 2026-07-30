-- Migration 002: auth foundation — users, device_tokens, conversations, chat_messages
-- Phase 2 (auth) groundwork. No app code depends on these tables yet — they exist
-- so the next PRs (device-token cookie, Google sign-in, chat-history persistence)
-- have somewhere to write.
--
-- Apply on EC2 as the postgres superuser (app roles only have USAGE, not CREATE,
-- on the public schema — see CLAUDE.md "DB role permissions gotcha"):
--   1. Add `local all postgres trust` to pg_hba.conf, reload postgres
--   2. psql -U postgres -d gaffer -f db/migrations/002_auth_tables.sql
--   3. Revert pg_hba.conf, reload postgres
--
-- SECURITY: these tables hold PII (email) and will later hold encrypted API keys
-- (Phase 3). Do NOT grant them to gaffer_readonly — that role backs the
-- query_database tool Claude uses to write arbitrary SQL over FPL data, and must
-- never be able to see this schema. Do NOT grant them to gaffer_etl either — that
-- role is scoped to the ETL pipeline. Instead this migration creates a new
-- least-privilege role, gaffer_app, for the FastAPI app's own read/write access.
-- Set its password via Secrets Manager (gaffer/production) before wiring
-- DATABASE_APP_URL in a follow-up PR — do not commit it here.

CREATE TABLE IF NOT EXISTS users (
    id             SERIAL PRIMARY KEY,
    google_sub     TEXT NOT NULL UNIQUE,   -- Google's stable subject id ("sub" claim)
    email          TEXT NOT NULL,
    name           TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at  TIMESTAMPTZ
);

COMMENT ON TABLE users IS
    'Signed-in Gaffer accounts. Created on first Google sign-in. '
    'NOT exposed to gaffer_readonly / query_database — contains PII.';


CREATE TABLE IF NOT EXISTS device_tokens (
    token        TEXT PRIMARY KEY,   -- opaque random value set as a cookie; same trust model as a session id
    user_id      INT REFERENCES users(id) ON DELETE CASCADE,   -- NULL until the device signs in
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE device_tokens IS
    'Anonymous per-browser identity, issued before sign-in so FPL team ID and '
    'chat history can persist without an account. user_id is set once the device '
    'signs in, merging its history into that account. '
    'NOT exposed to gaffer_readonly / query_database.';


CREATE TABLE IF NOT EXISTS conversations (
    id            SERIAL PRIMARY KEY,
    user_id       INT REFERENCES users(id) ON DELETE CASCADE,
    device_token  TEXT REFERENCES device_tokens(token) ON DELETE CASCADE,
    fpl_team_id   INT,
    title         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT conversations_owner_check
        CHECK (user_id IS NOT NULL OR device_token IS NOT NULL)
);

COMMENT ON TABLE conversations IS
    'One row per chat thread. Owned by exactly one of user_id (signed in) or '
    'device_token (anonymous) — never neither, and either may be set alongside '
    'the other once a device merges into an account. '
    'NOT exposed to gaffer_readonly / query_database.';

CREATE INDEX IF NOT EXISTS idx_conversations_user_id      ON conversations (user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_device_token ON conversations (device_token);


CREATE TABLE IF NOT EXISTS chat_messages (
    id               SERIAL PRIMARY KEY,
    conversation_id  INT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content          TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE chat_messages IS
    'Individual messages within a conversation, in role/content pairs matching '
    'the Claude message format. NOT exposed to gaffer_readonly / query_database.';

CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_created
    ON chat_messages (conversation_id, created_at);


-- ---------------------------------------------------------------------------
-- gaffer_app role — least-privilege access for the FastAPI app's own reads
-- and writes to the 4 tables above. No access to any FPL data table, and not
-- itself granted to gaffer_readonly or gaffer_etl.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gaffer_app') THEN
        CREATE ROLE gaffer_app LOGIN PASSWORD 'CHANGE_ME_VIA_SECRETS_MANAGER';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO gaffer_app;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON users, device_tokens, conversations, chat_messages
    TO gaffer_app;
GRANT SELECT, USAGE
    ON users_id_seq, conversations_id_seq, chat_messages_id_seq
    TO gaffer_app;
