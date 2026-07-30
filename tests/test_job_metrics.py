"""Tests for pipeline/job_metrics.py."""

from unittest.mock import AsyncMock, patch

from pipeline.job_metrics import (
    arecord_attempt,
    arecord_failure,
    arecord_success,
    record_attempt,
)


class TestArecordAttempt:
    async def test_returns_none_when_no_db_url(self):
        with patch("pipeline.job_metrics._db_url", return_value=""):
            assert await arecord_attempt("etl_snapshot") is None

    async def test_inserts_and_returns_id(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"id": 42}
        with (
            patch("pipeline.job_metrics._db_url", return_value="postgres://x"),
            patch("pipeline.job_metrics.asyncpg.connect", return_value=conn),
        ):
            run_id = await arecord_attempt("etl_snapshot")

        assert run_id == 42
        conn.fetchrow.assert_called_once()
        conn.close.assert_called_once()

    async def test_swallows_connection_errors(self):
        with (
            patch("pipeline.job_metrics._db_url", return_value="postgres://x"),
            patch("pipeline.job_metrics.asyncpg.connect", side_effect=Exception("boom")),
        ):
            assert await arecord_attempt("etl_snapshot") is None


class TestArecordSuccessFailure:
    async def test_success_noop_when_run_id_none(self):
        with patch("pipeline.job_metrics.asyncpg.connect") as mock_connect:
            await arecord_success(None)
        mock_connect.assert_not_called()

    async def test_failure_noop_when_run_id_none(self):
        with patch("pipeline.job_metrics.asyncpg.connect") as mock_connect:
            await arecord_failure(None, "some error")
        mock_connect.assert_not_called()

    async def test_success_updates_row(self):
        conn = AsyncMock()
        with (
            patch("pipeline.job_metrics._db_url", return_value="postgres://x"),
            patch("pipeline.job_metrics.asyncpg.connect", return_value=conn),
        ):
            await arecord_success(42, {"action": "synced"})
        conn.execute.assert_called_once()
        conn.close.assert_called_once()


class TestSyncWrappersCallable:
    def test_record_attempt_does_not_raise_outside_event_loop(self):
        # Regression test: record_attempt() must be callable from plain sync top-level
        # code (run_press_ingest.py, check_gw_complete.py), not from inside an already
        # running event loop — that's what arecord_attempt is for (see etl_v2.py).
        with patch("pipeline.job_metrics._db_url", return_value=""):
            assert record_attempt("some_job") is None
