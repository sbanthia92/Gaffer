"""Tests for pipeline/etl_v2.py's _validate_snapshot data-integrity check."""

from unittest.mock import AsyncMock

import pytest

from pipeline.etl_v2 import _validate_snapshot


def _bootstrap(n_players: int = 2, n_teams: int = 1) -> dict:
    return {
        "elements": [{"id": i, "total_points": 100 - i} for i in range(1, n_players + 1)],
        "teams": [{"id": i} for i in range(1, n_teams + 1)],
    }


class TestValidateSnapshot:
    async def test_passes_when_everything_matches(self):
        bootstrap = _bootstrap(n_players=2, n_teams=1)
        fixtures = [{"id": 1}, {"id": 2}]
        conn = AsyncMock()
        # player_count, team_count, fixture_count, top_scorer_points
        conn.fetchval.side_effect = [2, 1, 2, 99]

        await _validate_snapshot(conn, season_id=1, bootstrap=bootstrap, all_fixtures=fixtures)

    async def test_raises_on_player_count_mismatch(self):
        bootstrap = _bootstrap(n_players=2, n_teams=1)
        conn = AsyncMock()
        # player_count=1 (mismatch), team_count=1, fixture_count=0 — all three are
        # fetched before any check runs, so all three side effects must be present.
        conn.fetchval.side_effect = [1, 1, 0]

        with pytest.raises(RuntimeError, match="player count mismatch"):
            await _validate_snapshot(conn, season_id=1, bootstrap=bootstrap, all_fixtures=[])

    async def test_raises_on_team_count_mismatch(self):
        bootstrap = _bootstrap(n_players=2, n_teams=1)
        conn = AsyncMock()
        conn.fetchval.side_effect = [2, 0, 0]  # DB has 0 teams, FPL has 1

        with pytest.raises(RuntimeError, match="team count mismatch"):
            await _validate_snapshot(conn, season_id=1, bootstrap=bootstrap, all_fixtures=[])

    async def test_raises_on_fixture_count_mismatch(self):
        bootstrap = _bootstrap(n_players=2, n_teams=1)
        fixtures = [{"id": 1}, {"id": 2}]
        conn = AsyncMock()
        conn.fetchval.side_effect = [2, 1, 1]  # DB has 1 fixture, FPL has 2

        with pytest.raises(RuntimeError, match="fixture count mismatch"):
            await _validate_snapshot(conn, season_id=1, bootstrap=bootstrap, all_fixtures=fixtures)

    async def test_raises_on_top_scorer_points_mismatch(self):
        bootstrap = _bootstrap(n_players=2, n_teams=1)
        fixtures = [{"id": 1}, {"id": 2}]
        conn = AsyncMock()
        # counts all match, but the stored total_points for the top scorer is wrong
        conn.fetchval.side_effect = [2, 1, 2, 50]

        with pytest.raises(RuntimeError, match="total_points mismatch"):
            await _validate_snapshot(conn, season_id=1, bootstrap=bootstrap, all_fixtures=fixtures)
