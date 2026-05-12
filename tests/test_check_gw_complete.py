"""Tests for pipeline/check_gw_complete.py GW detection logic."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from pipeline.check_gw_complete import latest_finished_gw, main


def _event(gw_id: int, finished: bool, deadline_offset_days: int = -1) -> dict:
    """Build a minimal FPL event dict. deadline_offset_days < 0 means in the past."""
    deadline = (datetime.now(UTC) + timedelta(days=deadline_offset_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return {"id": gw_id, "finished": finished, "deadline_time": deadline}


class TestLatestFinishedGw:
    def test_returns_none_when_no_events(self):
        assert latest_finished_gw([]) is None

    def test_returns_none_when_none_finished(self):
        events = [_event(1, finished=False), _event(2, finished=False)]
        assert latest_finished_gw(events) is None

    def test_returns_highest_finished_gw(self):
        events = [
            _event(1, finished=True),
            _event(2, finished=True),
            _event(3, finished=False),
        ]
        assert latest_finished_gw(events) == 2

    def test_ignores_future_deadline_even_if_marked_finished(self):
        events = [
            _event(1, finished=True, deadline_offset_days=-1),
            _event(2, finished=True, deadline_offset_days=5),  # future deadline
        ]
        assert latest_finished_gw(events) == 1

    def test_returns_none_if_only_future_finished_events(self):
        events = [_event(1, finished=True, deadline_offset_days=5)]
        assert latest_finished_gw(events) is None

    def test_missing_deadline_time_is_skipped(self):
        events = [
            {"id": 1, "finished": True},  # no deadline_time
            _event(2, finished=True),
        ]
        assert latest_finished_gw(events) == 2


class TestMain:
    def _bootstrap_response(self, events: list[dict]) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"events": events}
        return resp

    @patch("pipeline.check_gw_complete._save_last_synced_gw")
    @patch("pipeline.check_gw_complete.subprocess.run")
    @patch("pipeline.check_gw_complete._load_last_synced_gw", return_value=0)
    @patch("pipeline.check_gw_complete.httpx.get")
    def test_triggers_etl_on_new_finished_gw(self, mock_get, mock_load, mock_run, mock_save):
        mock_get.return_value = self._bootstrap_response([_event(1, finished=True)])
        mock_run.return_value = MagicMock(returncode=0)

        main()

        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][-1] == "--mode=gw"
        mock_save.assert_called_once_with(1)

    @patch("pipeline.check_gw_complete._save_last_synced_gw")
    @patch("pipeline.check_gw_complete.subprocess.run")
    @patch("pipeline.check_gw_complete._load_last_synced_gw", return_value=3)
    @patch("pipeline.check_gw_complete.httpx.get")
    def test_skips_etl_when_already_synced(self, mock_get, mock_load, mock_run, mock_save):
        mock_get.return_value = self._bootstrap_response(
            [_event(1, finished=True), _event(2, finished=True), _event(3, finished=True)]
        )

        main()

        mock_run.assert_not_called()
        mock_save.assert_not_called()

    @patch("pipeline.check_gw_complete._save_last_synced_gw")
    @patch("pipeline.check_gw_complete.subprocess.run")
    @patch("pipeline.check_gw_complete._load_last_synced_gw", return_value=0)
    @patch("pipeline.check_gw_complete.httpx.get")
    def test_no_finished_gws_does_nothing(self, mock_get, mock_load, mock_run, mock_save):
        mock_get.return_value = self._bootstrap_response([_event(1, finished=False)])

        main()

        mock_run.assert_not_called()
        mock_save.assert_not_called()

    @patch("pipeline.check_gw_complete._save_last_synced_gw")
    @patch("pipeline.check_gw_complete.subprocess.run")
    @patch("pipeline.check_gw_complete._load_last_synced_gw", return_value=0)
    @patch("pipeline.check_gw_complete.httpx.get")
    def test_missing_state_file_treated_as_gw_zero(self, mock_get, mock_load, mock_run, mock_save):
        mock_get.return_value = self._bootstrap_response([_event(5, finished=True)])
        mock_run.return_value = MagicMock(returncode=0)

        main()

        mock_run.assert_called_once()
        mock_save.assert_called_once_with(5)

    @patch("pipeline.check_gw_complete._save_last_synced_gw")
    @patch("pipeline.check_gw_complete.subprocess.run")
    @patch("pipeline.check_gw_complete._load_last_synced_gw", return_value=0)
    @patch("pipeline.check_gw_complete.httpx.get")
    def test_does_not_update_state_file_on_etl_failure(
        self, mock_get, mock_load, mock_run, mock_save
    ):
        mock_get.return_value = self._bootstrap_response([_event(1, finished=True)])
        mock_run.return_value = MagicMock(returncode=1)

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        mock_save.assert_not_called()
