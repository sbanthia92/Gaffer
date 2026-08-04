"""
DB access for the auth tables (users, device_tokens) via the gaffer_app role
(DATABASE_APP_URL) — kept separate from the read-only FPL data pool in
server/tools/db.py.
"""

import secrets

import asyncpg

from server.config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    if not settings.database_app_url:
        return
    _pool = await asyncpg.create_pool(settings.database_app_url, min_size=1, max_size=5)


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def get_or_create_device_token(existing: str | None) -> str:
    """
    Validate an existing device token (touching last_seen_at) or issue a new one.
    Falls back to an unpersisted token if DATABASE_APP_URL isn't configured
    (local dev) — the cookie still round-trips, it just isn't tracked server-side.
    """
    if not _pool:
        return existing or secrets.token_urlsafe(32)

    async with _pool.acquire() as conn:
        if existing:
            row = await conn.fetchrow(
                "UPDATE device_tokens SET last_seen_at = NOW() WHERE token = $1 RETURNING token",
                existing,
            )
            if row:
                return row["token"]
        token = secrets.token_urlsafe(32)
        await conn.execute("INSERT INTO device_tokens (token) VALUES ($1)", token)
        return token


async def get_or_create_user(google_sub: str, email: str, name: str) -> int:
    """Upsert a user by their stable Google subject id, refreshing profile fields on each login."""
    if _pool is None:
        raise RuntimeError("DATABASE_APP_URL is not configured — Google sign-in requires it.")

    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (google_sub, email, name, last_login_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (google_sub) DO UPDATE
                SET email = EXCLUDED.email, name = EXCLUDED.name, last_login_at = NOW()
            RETURNING id
            """,
            google_sub,
            email,
            name,
        )
        return row["id"]


async def merge_device_into_user(device_token: str, user_id: int) -> None:
    """Link an anonymous device to the account it just signed into."""
    if _pool is None:
        raise RuntimeError("DATABASE_APP_URL is not configured — Google sign-in requires it.")

    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE device_tokens SET user_id = $1 WHERE token = $2", user_id, device_token
        )


async def upsert_conversation(
    client_session_id: str,
    device_token: str,
    user_id: int | None,
    fpl_team_id: int | None,
) -> int | None:
    """
    Best-effort — returns None if DATABASE_APP_URL isn't configured, so callers
    can skip persistence instead of crashing the chat response over it.

    NOTE: client_session_id is not scoped to device_token/user_id here — a
    client that already knew another session's UUID could in theory append to
    it. Not exploitable today since there's no read endpoint to leak IDs
    through, but a future read path must add that scoping before trusting
    this table for anything sensitive.
    """
    if _pool is None:
        return None

    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO conversations (client_session_id, device_token, user_id, fpl_team_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (client_session_id) DO UPDATE
                SET updated_at = NOW(),
                    user_id = COALESCE(conversations.user_id, EXCLUDED.user_id)
            RETURNING id
            """,
            client_session_id,
            device_token,
            user_id,
            fpl_team_id,
        )
        return row["id"]


async def save_chat_messages(conversation_id: int, question: str, answer: str) -> None:
    """Best-effort — no-ops if DATABASE_APP_URL isn't configured."""
    if _pool is None:
        return

    async with _pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO chat_messages (conversation_id, role, content) VALUES ($1, $2, $3)",
            [(conversation_id, "user", question), (conversation_id, "assistant", answer)],
        )
