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
