"""
DB access for the app-owned tables (users, device_tokens, conversations, chat_messages,
daily_question_counts) via the gaffer_app role
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
        # Chats started on this device before sign-in now belong to the account, so they
        # show up in the account's history on other devices.
        await conn.execute(
            "UPDATE conversations SET user_id = $1 WHERE device_token = $2 AND user_id IS NULL",
            user_id,
            device_token,
        )


# Conversations an account owns: its own, plus any still attributed only to a device
# linked to it (rows written before merge_device_into_user started backfilling user_id).
_OWNED_BY_USER = """
    (c.user_id = $1
     OR c.device_token IN (SELECT token FROM device_tokens WHERE user_id = $1))
"""


async def upsert_conversation(
    client_session_id: str,
    device_token: str,
    user_id: int | None,
    fpl_team_id: int | None,
) -> int | None:
    """
    Best-effort — returns None if DATABASE_APP_URL isn't configured, so callers
    can skip persistence instead of crashing the chat response over it.

    Also returns None when client_session_id already exists but belongs to a
    different device and a different (or no) account: the id comes from the
    client, so without this check anyone who learned another thread's UUID could
    append messages to it, and they would then show up in the owner's history.
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
                WHERE conversations.device_token = EXCLUDED.device_token
                   OR conversations.user_id = EXCLUDED.user_id
            RETURNING id
            """,
            client_session_id,
            device_token,
            user_id,
            fpl_team_id,
        )
        return row["id"] if row else None


async def save_chat_messages(conversation_id: int, question: str, answer: str) -> None:
    """Best-effort — no-ops if DATABASE_APP_URL isn't configured."""
    if _pool is None:
        return

    async with _pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO chat_messages (conversation_id, role, content) VALUES ($1, $2, $3)",
            [(conversation_id, "user", question), (conversation_id, "assistant", answer)],
        )


async def count_question(usage_key: str) -> int | None:
    """
    Record one question against today's (UTC) allowance for usage_key and return the
    new total. Returns None if DATABASE_APP_URL isn't configured, so local dev has
    no daily limit.
    """
    if _pool is None:
        return None

    async with _pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO daily_question_counts (usage_key, day, question_count)
            VALUES ($1, (NOW() AT TIME ZONE 'UTC')::date, 1)
            ON CONFLICT (usage_key, day) DO UPDATE
                SET question_count = daily_question_counts.question_count + 1
            RETURNING question_count
            """,
            usage_key,
        )


def group_conversation_rows(rows: list) -> list[dict]:
    """Fold conversation⋈message rows (ordered by conversation, then message) into threads."""
    conversations: dict[str, dict] = {}
    for row in rows:
        conversation = conversations.setdefault(
            row["client_session_id"],
            {
                "id": row["client_session_id"],
                "created_at": int(row["created_at"].timestamp() * 1000),
                "updated_at": int(row["updated_at"].timestamp() * 1000),
                "messages": [],
            },
        )
        conversation["messages"].append(
            {
                "id": f"srv-{row['message_id']}",
                "role": row["role"],
                "content": row["content"],
                "created_at": int(row["message_created_at"].timestamp() * 1000),
            }
        )
    return list(conversations.values())


async def list_conversations(user_id: int, limit: int = 50) -> list[dict]:
    """The account's most recently updated threads with their messages, newest thread first."""
    if _pool is None:
        return []

    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            WITH recent AS (
                SELECT c.id, c.client_session_id, c.created_at, c.updated_at
                FROM conversations c
                WHERE c.client_session_id IS NOT NULL AND {_OWNED_BY_USER}
                ORDER BY c.updated_at DESC
                LIMIT $2
            )
            SELECT r.client_session_id, r.created_at, r.updated_at,
                   m.id AS message_id, m.role, m.content, m.created_at AS message_created_at
            FROM recent r
            JOIN chat_messages m ON m.conversation_id = r.id
            ORDER BY r.updated_at DESC, r.id, m.id
            """,
            user_id,
            limit,
        )
    return group_conversation_rows(rows)


async def delete_conversation(user_id: int, client_session_id: str) -> bool:
    """Delete one of the account's threads (messages cascade). False if it isn't theirs."""
    if _pool is None:
        return False

    async with _pool.acquire() as conn:
        deleted = await conn.fetchval(
            f"""
            DELETE FROM conversations c
            WHERE c.client_session_id = $2 AND {_OWNED_BY_USER}
            RETURNING c.id
            """,
            user_id,
            client_session_id,
        )
    return deleted is not None
