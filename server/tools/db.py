"""
Internal DB utility — read-only asyncpg pool used by FPL tools.

Not exposed to Claude as a tool. Claude uses query_historical_stats
from sports-context-mcp for ad-hoc SQL queries instead.
"""

import re
from datetime import date, datetime
from decimal import Decimal

import asyncpg

from server.config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    if not settings.database_url:
        return
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
        server_settings={"statement_timeout": str(_TIMEOUT_MS)},
    )


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


_BANNED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE"
    r"|EXEC|EXECUTE|pg_read_file|COPY)\b",
    re.IGNORECASE,
)
_MAX_ROWS = 50
_TIMEOUT_MS = 10_000


async def execute(sql: str, params: tuple = ()) -> dict:
    """Execute a read-only SQL query and return results as a list of dicts."""
    sql = sql.strip()

    if _BANNED.search(sql):
        return {"error": True, "message": "Query blocked: only SELECT statements are permitted."}

    if not sql.upper().startswith("SELECT"):
        return {"error": True, "message": "Query blocked: must begin with SELECT."}

    if not settings.database_url:
        return {"error": True, "message": "Database not configured (DATABASE_URL missing)."}

    try:
        if _pool:
            async with _pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
        else:
            conn = await asyncpg.connect(settings.database_url)
            try:
                await conn.execute(f"SET statement_timeout = {_TIMEOUT_MS}")
                rows = await conn.fetch(sql, *params)
            finally:
                await conn.close()
    except asyncpg.PostgresError as e:
        return {"error": True, "message": f"Database error: {e}"}
    except Exception as e:
        return {"error": True, "message": f"Query failed: {e}"}

    if not rows:
        return {"rows": [], "row_count": 0}

    def _serialize(v):
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, date):
            return v.isoformat()
        return v

    result = [{k: _serialize(v) for k, v in dict(row).items()} for row in rows[:_MAX_ROWS]]
    return {
        "rows": result,
        "row_count": len(result),
        "truncated": len(rows) > _MAX_ROWS,
    }
