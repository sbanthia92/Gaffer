"""
Record job run events to the job_runs PostgreSQL table.

Each pipeline script calls record_attempt() at the top, then record_success()
or record_failure() depending on outcome. record_attempt/success/failure are
synchronous wrappers around asyncpg for scripts with a synchronous top level
(run_press_ingest.py, check_gw_complete.py). Scripts that are already async at
the top level (etl_v2.py's main()) must use the arecord_* coroutines directly —
the sync wrappers call asyncio.run() internally and cannot be invoked from
inside an already-running event loop.

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


async def arecord_attempt(job_name: str, *, gw_number: int | None = None) -> int | None:
    """Async: insert an 'attempt' row and return its id (None if DB unavailable)."""
    url = _db_url()
    if not url:
        return None
    try:
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
    except Exception as exc:
        log.warning("job_metrics.record_attempt failed: %s", exc)
        return None


async def arecord_success(run_id: int | None, details: dict[str, Any] | None = None) -> None:
    """Async: mark a run as successful."""
    if run_id is None:
        return
    url = _db_url()
    if not url:
        return
    try:
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
    except Exception as exc:
        log.warning("job_metrics.record_success failed: %s", exc)


async def arecord_failure(run_id: int | None, error: str) -> None:
    """Async: mark a run as failed, storing the error message in details."""
    if run_id is None:
        return
    url = _db_url()
    if not url:
        return
    try:
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
    except Exception as exc:
        log.warning("job_metrics.record_failure failed: %s", exc)


def record_attempt(job_name: str, *, gw_number: int | None = None) -> int | None:
    """Sync wrapper for non-async scripts. See arecord_attempt for async callers."""
    return asyncio.run(arecord_attempt(job_name, gw_number=gw_number))


def record_success(run_id: int | None, details: dict[str, Any] | None = None) -> None:
    """Sync wrapper for non-async scripts. See arecord_success for async callers."""
    asyncio.run(arecord_success(run_id, details))


def record_failure(run_id: int | None, error: str) -> None:
    """Sync wrapper for non-async scripts. See arecord_failure for async callers."""
    asyncio.run(arecord_failure(run_id, error))
