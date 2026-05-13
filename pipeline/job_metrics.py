"""
Record job run events to the job_runs PostgreSQL table.

Each pipeline script calls record_attempt() at the top, then record_success()
or record_failure() depending on outcome.  All functions are synchronous wrappers
around asyncpg so they can be called from non-async scripts without refactoring.

Errors in metric recording are logged and swallowed — a metrics failure must never
abort the actual job.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import asyncpg

log = logging.getLogger(__name__)


def _db_url() -> str:
    from server.config import settings

    return settings.database_etl_url or settings.database_url


def record_attempt(job_name: str, *, gw_number: int | None = None) -> int | None:
    """Insert an 'attempt' row and return its id (None if DB unavailable)."""

    async def _run() -> int | None:
        url = _db_url()
        if not url:
            return None
        conn = await asyncpg.connect(url)
        try:
            row = await conn.fetchrow(
                "INSERT INTO job_runs (job_name, status, gw_number)"
                " VALUES ($1, 'attempt', $2) RETURNING id",
                job_name,
                gw_number,
            )
            return row["id"] if row else None
        finally:
            await conn.close()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        log.warning("job_metrics.record_attempt failed: %s", exc)
        return None


def record_success(run_id: int | None, details: dict[str, Any] | None = None) -> None:
    """Mark a run as successful."""
    if run_id is None:
        return

    async def _run() -> None:
        url = _db_url()
        if not url:
            return
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(
                "UPDATE job_runs SET status='success', details=$1::jsonb, completed_at=$2"
                " WHERE id=$3",
                json.dumps(details or {}),
                datetime.now(UTC),
                run_id,
            )
        finally:
            await conn.close()

    try:
        asyncio.run(_run())
    except Exception as exc:
        log.warning("job_metrics.record_success failed: %s", exc)


def record_failure(run_id: int | None, error: str) -> None:
    """Mark a run as failed, storing the error message in details."""
    if run_id is None:
        return

    async def _run() -> None:
        url = _db_url()
        if not url:
            return
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(
                "UPDATE job_runs SET status='failure', details=$1::jsonb, completed_at=$2"
                " WHERE id=$3",
                json.dumps({"error": error}),
                datetime.now(UTC),
                run_id,
            )
        finally:
            await conn.close()

    try:
        asyncio.run(_run())
    except Exception as exc:
        log.warning("job_metrics.record_failure failed: %s", exc)
