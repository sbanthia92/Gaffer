from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from server.tools.fpl import (
    TOOL_DEFINITIONS,
    analyse_mini_league,
    get_captain_options,
    get_fixtures,
    get_gameweek_schedule,
    get_head_to_head,
    get_mini_league_standings,
    get_my_fpl_team,
    get_player_recent_form,
    get_player_stats,
    get_player_vs_opponent,
    get_price_changes,
    get_standings,
    get_team_all_fixtures,
    get_team_recent_fixtures,
    plan_chips,
    search_players_by_criteria,
)

_FPL_BASE = "https://fantasy.premierleague.com/api"

# Minimal bootstrap with two teams
_BOOTSTRAP_TWO_TEAMS = {
    "events": [],
    "teams": [
        {"id": 8, "name": "Chelsea", "short_name": "CHE"},
        {"id": 1, "name": "Arsenal", "short_name": "ARS"},
    ],
    "elements": [],
}

# A finished fixture between Chelsea (home) and Arsenal (away), 2-1
_FINISHED_FIXTURE = {
    "id": 42,
    "event": 30,
    "finished": True,
    "started": True,
    "kickoff_time": "2026-03-30T15:00:00+00:00",
    "team_h": 8,
    "team_a": 1,
    "team_h_score": 2,
    "team_a_score": 1,
    "team_h_difficulty": 3,
    "team_a_difficulty": 4,
}

# An upcoming fixture (not started)
_UPCOMING_FIXTURE = {
    "id": 99,
    "event": 35,
    "finished": False,
    "started": False,
    "kickoff_time": "2026-04-15T20:00:00+00:00",
    "team_h": 8,
    "team_a": 1,
    "team_h_difficulty": 2,
    "team_a_difficulty": 3,
}


@pytest.mark.asyncio
async def test_get_fixtures_returns_trimmed_response():
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=_BOOTSTRAP_TWO_TEAMS)
        )
        respx.get(f"{_FPL_BASE}/fixtures/").mock(
            return_value=httpx.Response(200, json=[_UPCOMING_FIXTURE])
        )
        result = await get_fixtures(next_n=5)

    assert "fixtures" in result
    assert len(result["fixtures"]) == 1
    f = result["fixtures"][0]
    assert f["home"] == "Chelsea"
    assert f["away"] == "Arsenal"
    assert f["date"] == "2026-04-15"
    assert f["home_difficulty"] == 2
    assert f["away_difficulty"] == 3


@pytest.mark.asyncio
async def test_get_standings_returns_trimmed_response():
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    fpl_mod._slow_cache.clear()
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=_BOOTSTRAP_TWO_TEAMS)
        )
        respx.get(f"{_FPL_BASE}/fixtures/").mock(
            return_value=httpx.Response(200, json=[_FINISHED_FIXTURE])
        )
        result = await get_standings()

    assert "standings" in result
    rows = {r["team"]: r for r in result["standings"]}
    # Chelsea won 2-1: 3 pts, GD +1
    assert rows["Chelsea"]["won"] == 1
    assert rows["Chelsea"]["points"] == 3
    assert rows["Chelsea"]["goal_difference"] == 1
    assert rows["Chelsea"]["rank"] == 1
    # Arsenal lost: 0 pts
    assert rows["Arsenal"]["lost"] == 1
    assert rows["Arsenal"]["points"] == 0
    assert rows["Arsenal"]["rank"] == 2


async def _standings_with_previous_season(previous_rows: dict) -> dict:
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    fpl_mod._slow_cache.clear()
    with (
        respx.mock,
        patch("server.tools.db.execute", new=AsyncMock(return_value=previous_rows)),
    ):
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=_BOOTSTRAP_TWO_TEAMS)
        )
        respx.get(f"{_FPL_BASE}/fixtures/").mock(
            return_value=httpx.Response(200, json=[_FINISHED_FIXTURE])
        )
        result = await get_standings()
    fpl_mod._slow_cache.clear()
    return result


@pytest.mark.asyncio
async def test_get_standings_flags_clubs_new_to_league():
    # Last season had Arsenal + Leeds; Chelsea is new this season.
    result = await _standings_with_previous_season(
        {"rows": [{"name": "Arsenal"}, {"name": "Leeds"}], "row_count": 2}
    )
    assert result["new_to_league_this_season"] == ["Chelsea"]


@pytest.mark.asyncio
async def test_get_standings_reports_no_new_clubs_when_teams_unchanged():
    result = await _standings_with_previous_season(
        {"rows": [{"name": "Arsenal"}, {"name": "Chelsea"}], "row_count": 2}
    )
    assert result["new_to_league_this_season"] == []


@pytest.mark.asyncio
async def test_get_standings_omits_new_clubs_when_last_season_unknown():
    # DB unavailable / last season's teams never stored: unknown, so say nothing.
    result = await _standings_with_previous_season({"error": True, "message": "no db"})
    assert "new_to_league_this_season" not in result
    assert len(result["standings"]) == 2


@pytest.mark.asyncio
async def test_get_player_stats_returns_fpl_data():
    bootstrap = {
        "elements": [
            {
                "id": 328,
                "first_name": "Erling",
                "second_name": "Haaland",
                "web_name": "Haaland",
                "team": 1,
                "element_type": 4,
            }
        ],
        "teams": [{"id": 1, "name": "Man City", "short_name": "MCI"}],
        "events": [],
    }
    db_result = {
        "rows": [
            {
                "web_name": "Haaland",
                "team": "Man City",
                "position": "FWD",
                "price": 14.0,
                "total_points": 180,
                "minutes": 2340,
                "goals_scored": 22,
                "assists": 5,
                "clean_sheets": 0,
                "bonus": 28,
                "xg": 18.5,
                "xa": 3.2,
            }
        ],
        "row_count": 1,
    }

    from unittest.mock import AsyncMock, patch

    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        with patch("server.tools.db.execute", new=AsyncMock(return_value=db_result)):
            result = await get_player_stats(player_name="Haaland")

    assert "player_stats" in result
    assert result["player_stats"]["goals_scored"] == 22
    assert result["player_stats"]["team"] == "Man City"
    assert result["player_stats"]["total_points"] == 180


@pytest.mark.asyncio
async def test_get_player_recent_form_returns_per_game_stats():
    bootstrap = {
        "elements": [
            {
                "id": 328,
                "first_name": "Erling",
                "second_name": "Haaland",
                "web_name": "Haaland",
                "team": 1,
                "element_type": 4,
            }
        ],
        "teams": [{"id": 1, "name": "Man City"}],
        "events": [],
    }
    element_summary = {
        "history": [
            {
                "round": 33,
                "opponent_team": 7,
                "was_home": True,
                "minutes": 90,
                "goals_scored": 2,
                "assists": 0,
                "clean_sheets": 0,
                "goals_conceded": 1,
                "yellow_cards": 0,
                "red_cards": 0,
                "bonus": 3,
                "total_points": 14,
            }
        ]
    }
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None  # force fresh fetch
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        respx.get(f"{_FPL_BASE}/element-summary/328/").mock(
            return_value=httpx.Response(200, json=element_summary)
        )
        result = await get_player_recent_form(player_name="Haaland", last_n=1)
    assert "recent_form" in result
    assert result["recent_form"][0]["goals"] == 2
    assert result["recent_form"][0]["minutes"] == 90
    assert result["recent_form"][0]["total_points"] == 14
    assert result["recent_form"][0]["bonus"] == 3
    assert result["player"] == "Erling Haaland"


@pytest.mark.asyncio
async def test_get_team_recent_fixtures_returns_trimmed_response():
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=_BOOTSTRAP_TWO_TEAMS)
        )
        respx.get(f"{_FPL_BASE}/fixtures/").mock(
            return_value=httpx.Response(200, json=[_FINISHED_FIXTURE])
        )
        result = await get_team_recent_fixtures(team_name="Chelsea", last_n=5)

    assert "recent_fixtures" in result
    assert len(result["recent_fixtures"]) == 1
    f = result["recent_fixtures"][0]
    assert f["home"] == "Chelsea"
    assert f["away"] == "Arsenal"
    assert f["home_goals"] == 2
    assert f["away_goals"] == 1
    assert f["home_winner"] is True
    assert f["away_winner"] is False


@pytest.mark.asyncio
async def test_get_head_to_head_returns_trimmed_response():
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=_BOOTSTRAP_TWO_TEAMS)
        )
        respx.get(f"{_FPL_BASE}/fixtures/").mock(
            return_value=httpx.Response(200, json=[_FINISHED_FIXTURE])
        )
        result = await get_head_to_head(team1_name="Chelsea", team2_name="Arsenal", last_n=5)

    assert "h2h" in result
    assert len(result["h2h"]) == 1
    f = result["h2h"][0]
    assert f["home"] == "Chelsea"
    assert f["away"] == "Arsenal"
    assert f["home_goals"] == 2
    assert f["away_goals"] == 1


@pytest.mark.asyncio
async def test_get_team_all_fixtures_returns_all_competitions():
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=_BOOTSTRAP_TWO_TEAMS)
        )
        respx.get(f"{_FPL_BASE}/fixtures/").mock(
            return_value=httpx.Response(200, json=[_UPCOMING_FIXTURE])
        )
        result = await get_team_all_fixtures(team_name="Chelsea", next_n=7)

    assert "all_fixtures" in result
    assert len(result["all_fixtures"]) == 1
    f = result["all_fixtures"][0]
    assert f["competition"] == "Premier League"
    assert f["home"] == "Chelsea"
    assert f["away"] == "Arsenal"
    assert f["difficulty"] == 2


@pytest.mark.asyncio
async def test_get_player_vs_opponent_returns_per_game_stats():
    bootstrap = {
        "elements": [
            {
                "id": 328,
                "first_name": "Erling",
                "second_name": "Haaland",
                "web_name": "Haaland",
                "team": 1,
                "element_type": 4,
            }
        ],
        "teams": [
            {"id": 1, "name": "Man City", "short_name": "MCI"},
            {"id": 7, "name": "Chelsea", "short_name": "CHE"},
        ],
        "events": [],
    }
    db_result = {
        "rows": [
            {
                "season": "2024/25",
                "start_year": 2024,
                "gw_number": 28,
                "home_away": "H",
                "minutes": 90,
                "goals_scored": 2,
                "assists": 0,
                "clean_sheets": 1,
                "goals_conceded": 0,
                "bonus": 3,
                "total_points": 15,
                "xg": 1.23,
                "xa": 0.11,
                "starts": 1,
            }
        ],
        "row_count": 1,
    }

    from unittest.mock import AsyncMock, patch

    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        with patch("server.tools.db.execute", new=AsyncMock(return_value=db_result)):
            result = await get_player_vs_opponent(
                player_name="Haaland", opponent_name="Chelsea", last_n=5
            )

    assert result["player"] == "Erling Haaland"
    assert result["opponent"] == "Chelsea"
    assert result["games"][0]["season"] == "2024/25"
    assert result["games"][0]["goals_scored"] == 2
    assert result["games"][0]["total_points"] == 15
    assert result["games"][0]["minutes"] == 90


_BOOTSTRAP = {
    "events": [{"id": 36, "is_current": True, "is_next": False}],
    "teams": [{"id": 43, "name": "Man City"}],
    "elements": [
        {
            "id": 350,
            "first_name": "Erling",
            "second_name": "Haaland",
            "team": 43,
            "element_type": 4,
        }
    ],
}

_PICKS = {
    "active_chip": None,
    "picks": [
        {
            "element": 350,
            "selling_price": 140,
            "multiplier": 2,
            "is_captain": True,
            "is_vice_captain": False,
        }
    ],
}


_ENTRY = {
    "leagues": {
        "classic": [
            {
                "id": 999,
                "name": "Office League",
                "league_type": "c",
                "entry_rank": 3,
                "entry_last_rank": 4,
            },  # noqa: E501
            {
                "id": 314,
                "name": "Overall",
                "league_type": "x",
                "entry_rank": 500000,
                "entry_last_rank": 501000,
            },  # noqa: E501
        ]
    }
}


@pytest.mark.asyncio
async def test_get_my_fpl_team_returns_squad():
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=_BOOTSTRAP)
        )
        respx.get(f"{_FPL_BASE}/entry/123/event/36/picks/").mock(
            return_value=httpx.Response(200, json=_PICKS)
        )
        respx.get(f"{_FPL_BASE}/entry/123/").mock(return_value=httpx.Response(200, json=_ENTRY))
        with patch("server.tools.fpl.settings") as mock_settings:
            mock_settings.fpl_team_id = 123
            result = await get_my_fpl_team()
    assert result["gameweek"] == 36
    assert result["squad"][0]["name"] == "Erling Haaland"
    assert result["squad"][0]["is_captain"] is True
    assert result["squad"][0]["selling_price"] == 14.0
    assert result["my_leagues"] == [
        {"id": 999, "name": "Office League", "entry_rank": 3, "entry_last_rank": 4}
    ]


@pytest.mark.asyncio
async def test_get_my_fpl_team_no_team_id():
    with patch("server.tools.fpl.settings") as mock_settings:
        mock_settings.fpl_team_id = None
        result = await get_my_fpl_team()
    assert "error" in result


@pytest.mark.asyncio
async def test_api_error_raises():
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(return_value=httpx.Response(401))
        with pytest.raises(httpx.HTTPStatusError):
            await get_fixtures()


@pytest.mark.asyncio
async def test_search_players_by_criteria_sorts_by_form_and_includes_defensive_stats():
    bootstrap = {
        "elements": [
            {
                "id": 1,
                "web_name": "Salah",
                "team": 10,
                "element_type": 3,
                "now_cost": 130,
                "total_points": 200,
                "event_points": 12,
                "points_per_game": "8.5",
                "form": "5.0",
                "minutes": 2700,
                "goals_scored": 18,
                "assists": 10,
                "clean_sheets": 3,
                "bonus": 25,
                "saves": 0,
                "expected_goals": "15.2",
                "expected_assists": "8.1",
                "expected_goal_involvements": "23.3",
                "ict_index": "310.5",
                "selected_by_percent": "45.0",
                "transfers_in_event": 50000,
                "transfers_out_event": 10000,
                "status": "a",
                "news": "",
                "chance_of_playing_this_round": None,
            },
            {
                "id": 2,
                "web_name": "Trent",
                "team": 10,
                "element_type": 2,
                "now_cost": 75,
                "total_points": 120,
                "event_points": 6,
                "points_per_game": "5.0",
                "form": "8.0",
                "minutes": 2000,
                "goals_scored": 2,
                "assists": 8,
                "clean_sheets": 10,
                "bonus": 12,
                "saves": 0,
                "expected_goals": "1.5",
                "expected_assists": "6.0",
                "expected_goal_involvements": "7.5",
                "ict_index": "150.0",
                "selected_by_percent": "30.0",
                "transfers_in_event": 20000,
                "transfers_out_event": 5000,
                "status": "a",
                "news": "",
                "chance_of_playing_this_round": None,
            },
        ],
        "teams": [{"id": 10, "short_name": "LIV"}],
        "events": [],
    }
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        result = await search_players_by_criteria(position="DEF", max_price=8.0)

    assert "players" in result
    assert len(result["players"]) == 1
    p = result["players"][0]
    assert p["name"] == "Trent"
    assert p["clean_sheets"] == 10
    assert p["bonus"] == 12
    assert p["saves"] == 0


@pytest.mark.asyncio
async def test_search_players_by_criteria_form_sort():
    bootstrap = {
        "elements": [
            {
                "id": 1,
                "web_name": "PlayerA",
                "team": 1,
                "element_type": 4,
                "now_cost": 80,
                "total_points": 150,
                "event_points": 6,
                "points_per_game": "6.0",
                "form": "4.0",
                "minutes": 2500,
                "goals_scored": 10,
                "assists": 3,
                "clean_sheets": 0,
                "bonus": 8,
                "saves": 0,
                "expected_goals": "9.0",
                "expected_assists": "2.5",
                "expected_goal_involvements": "11.5",
                "ict_index": "200.0",
                "selected_by_percent": "20.0",
                "transfers_in_event": 1000,
                "transfers_out_event": 500,
                "status": "a",
                "news": "",
                "chance_of_playing_this_round": None,
            },
            {
                "id": 2,
                "web_name": "PlayerB",
                "team": 2,
                "element_type": 4,
                "now_cost": 70,
                "total_points": 80,
                "event_points": 14,
                "points_per_game": "7.0",
                "form": "9.5",
                "minutes": 1800,
                "goals_scored": 7,
                "assists": 2,
                "clean_sheets": 0,
                "bonus": 15,
                "saves": 0,
                "expected_goals": "6.0",
                "expected_assists": "1.5",
                "expected_goal_involvements": "7.5",
                "ict_index": "180.0",
                "selected_by_percent": "10.0",
                "transfers_in_event": 5000,
                "transfers_out_event": 200,
                "status": "a",
                "news": "",
                "chance_of_playing_this_round": None,
            },
        ],
        "teams": [{"id": 1, "short_name": "MCY"}, {"id": 2, "short_name": "AVL"}],
        "events": [],
    }
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        result = await search_players_by_criteria(position="FWD")

    # PlayerB has lower total_points but higher form — should rank first
    assert result["players"][0]["name"] == "PlayerB"
    assert result["players"][1]["name"] == "PlayerA"


@pytest.mark.asyncio
async def test_get_gameweek_schedule_includes_difficulty_and_skips_unscheduled_blanks():
    bootstrap = {
        "events": [
            {
                "id": 36,
                "is_current": True,
                "is_next": False,
                "deadline_time": "2026-04-28T17:30:00Z",
            },  # noqa: E501
            {
                "id": 37,
                "is_current": False,
                "is_next": True,
                "deadline_time": "2026-05-05T17:30:00Z",
            },  # noqa: E501
        ],
        "teams": [
            {"id": 1, "short_name": "ARS"},
            {"id": 2, "short_name": "CHE"},
            {"id": 3, "short_name": "LIV"},
        ],
        "elements": [],
    }
    # GW36 has one fixture; GW37 has no fixtures assigned yet (unscheduled)
    fixtures = [
        {
            "event": 36,
            "team_h": 1,
            "team_a": 2,
            "team_h_difficulty": 3,
            "team_a_difficulty": 4,
        }
    ]
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    fpl_mod._slow_cache.clear()
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        respx.get(f"{_FPL_BASE}/fixtures/").mock(return_value=httpx.Response(200, json=fixtures))
        result = await get_gameweek_schedule(next_n=2)

    schedule = result["gameweek_schedule"]
    assert len(schedule) == 2

    gw36 = schedule[0]
    assert gw36["gameweek"] == 36
    # Fixtures now include difficulty
    assert gw36["fixtures"][0]["home"] == "ARS"
    assert gw36["fixtures"][0]["away"] == "CHE"
    assert gw36["fixtures"][0]["home_difficulty"] == 3
    assert gw36["fixtures"][0]["away_difficulty"] == 4
    # LIV has no fixture in GW36 → genuine blank
    assert "LIV" in gw36["blank_gameweek_teams"]
    assert gw36["is_blank_gw"] is True

    gw37 = schedule[1]
    # GW37 has no fixtures assigned → not a blank, just unscheduled
    assert gw37["blank_gameweek_teams"] == []
    assert gw37["is_blank_gw"] is False


@pytest.mark.asyncio
async def test_get_mini_league_standings_returns_standings():
    with respx.mock:
        respx.get(f"{_FPL_BASE}/leagues-classic/12345/standings/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "league": {"id": 12345, "name": "Office League"},
                    "standings": {
                        "has_next": False,
                        "results": [
                            {
                                "rank": 1,
                                "last_rank": 2,
                                "player_name": "Alice Smith",
                                "entry_name": "Alice FC",
                                "total": 1850,
                                "event_total": 72,
                            },
                            {
                                "rank": 2,
                                "last_rank": 1,
                                "player_name": "Bob Jones",
                                "entry_name": "Bob United",
                                "total": 1820,
                                "event_total": 55,
                            },
                        ],
                    },
                },
            )
        )
        result = await get_mini_league_standings(league_id=12345)
    assert result["league_name"] == "Office League"
    assert result["league_id"] == 12345
    assert len(result["standings"]) == 2
    assert result["standings"][0]["rank"] == 1
    assert result["standings"][0]["manager"] == "Alice Smith"
    assert result["standings"][0]["team_name"] == "Alice FC"
    assert result["standings"][0]["total_points"] == 1850
    assert result["standings"][0]["gw_points"] == 72
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_get_captain_options_returns_ranked_candidates():
    bootstrap = {
        "events": [
            {"id": 36, "is_current": True, "is_next": False},
            {"id": 37, "is_current": False, "is_next": True},
        ],
        "teams": [
            {"id": 1, "name": "Liverpool", "short_name": "LIV"},
            {"id": 2, "name": "Man City", "short_name": "MCI"},
            {"id": 3, "name": "Arsenal", "short_name": "ARS"},
        ],
        "elements": [
            {
                "id": 10,
                "first_name": "Mohamed",
                "second_name": "Salah",
                "web_name": "Salah",
                "team": 1,
                "element_type": 3,
                "now_cost": 130,
                "form": "9.2",
                "selected_by_percent": "45.0",
                "status": "a",
                "chance_of_playing_this_round": None,
            },
            {
                "id": 20,
                "first_name": "Erling",
                "second_name": "Haaland",
                "web_name": "Haaland",
                "team": 2,
                "element_type": 4,
                "now_cost": 150,
                "form": "7.0",
                "selected_by_percent": "60.0",
                "status": "a",
                "chance_of_playing_this_round": None,
            },
        ],
    }
    fixtures_gw37 = [
        {"team_h": 1, "team_a": 3, "team_h_difficulty": 2, "team_a_difficulty": 4},
        {"team_h": 2, "team_a": 3, "team_h_difficulty": 3, "team_a_difficulty": 4},
    ]
    salah_summary = {"history": [{"total_points": p} for p in [8, 12, 6, 15, 10]]}
    haaland_summary = {"history": [{"total_points": p} for p in [2, 8, 9, 6, 7]]}

    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(  # noqa: E501
            return_value=httpx.Response(200, json=bootstrap)
        )
        respx.get(f"{_FPL_BASE}/fixtures/").mock(
            return_value=httpx.Response(200, json=fixtures_gw37)
        )
        respx.get(f"{_FPL_BASE}/element-summary/10/").mock(
            return_value=httpx.Response(200, json=salah_summary)
        )
        respx.get(f"{_FPL_BASE}/element-summary/20/").mock(
            return_value=httpx.Response(200, json=haaland_summary)
        )
        result = await get_captain_options(["Salah", "Haaland"])

    assert result["gameweek"] == 37
    # Salah last-5 total = 51, Haaland = 32 → Salah ranked first
    assert result["captain_options"][0]["name"] == "Salah"
    assert result["captain_options"][0]["last_5_total"] == 51
    assert result["captain_options"][0]["next_fixture_opponent"] == "ARS"
    assert result["captain_options"][0]["next_fixture_difficulty"] == 2
    assert result["captain_options"][1]["name"] == "Haaland"
    assert result["not_found"] == []


def _xpts_row(name: str) -> dict:
    return {
        "web_name": name,
        "position": "MID",
        "team_name": "Arsenal",
        "price": 7.0,
        "xpts": 5.0,
        "xpts_goals": 1.0,
        "xpts_assists": 1.0,
        "xpts_cs": 0.5,
        "xpts_saves": 0,
        "xpts_bonus": 0.5,
        "xpts_minutes": 2.0,
        "status": "a",
        "chance_of_playing_next_round": None,
        "opponents": ["Spurs"],
        "fdrs": [3],
        "home_flags": [True],
        "gw_number": 10,
        "sample_gws": 5,
        "avg_xg_per_start": 0.2,
        "avg_xa_per_start": 0.1,
        "avg_minutes_per_start": 85,
    }


@pytest.mark.asyncio
async def test_get_player_xpts_limit_covers_all_named_players():
    from unittest.mock import AsyncMock, patch

    from server.tools.fpl import get_player_xpts

    names = [f"P{i}" for i in range(15)]
    mock = AsyncMock(return_value={"rows": [_xpts_row("P0")]})
    with patch("server.tools.db.execute", new=mock):
        await get_player_xpts(player_names=names)

    assert mock.call_args.args[1][-1] == 30  # not the default top_n of 10


@pytest.mark.asyncio
async def test_get_player_xpts_reports_not_found():
    from unittest.mock import AsyncMock, patch

    from server.tools.fpl import get_player_xpts

    mock = AsyncMock(return_value={"rows": [_xpts_row("Saka")]})
    with patch("server.tools.db.execute", new=mock):
        result = await get_player_xpts(player_names=["Saka", "Delap"])

    assert result["not_found"] == ["Delap"]
    assert [p["name"] for p in result["players"]] == ["Saka"]


@pytest.mark.asyncio
async def test_get_player_xpts_no_not_found_key_when_all_match():
    from unittest.mock import AsyncMock, patch

    from server.tools.fpl import get_player_xpts

    mock = AsyncMock(return_value={"rows": [_xpts_row("Saka")]})
    with patch("server.tools.db.execute", new=mock):
        result = await get_player_xpts(player_names=["saka"])

    assert "not_found" not in result


def test_tool_definitions_structure():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert names == {
        "get_my_fpl_team",
        "get_chip_status",
        "plan_chips",
        "analyse_mini_league",
        "get_price_changes",
        "get_gameweek_schedule",
        "get_fixtures",
        "get_standings",
        "get_player_stats",
        "get_player_recent_form",
        "get_team_recent_fixtures",
        "get_team_all_fixtures",
        "get_head_to_head",
        "get_player_vs_opponent",
        "search_players_by_criteria",
        "get_mini_league_standings",
        "get_captain_options",
        "get_player_xpts",
    }
    for tool in TOOL_DEFINITIONS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool


def _chip_squad() -> list[dict]:
    def p(name, team, mult, ppg="5.0", status="a"):
        return {
            "web_name": name,
            "name": name,
            "team": team,
            "multiplier": mult,
            "points_per_game": ppg,
            "status": status,
        }

    return [
        p("Salah", "Liverpool", 2, "8.0"),
        p("Saka", "Arsenal", 1, "6.0"),
        p("Benchy", "Arsenal", 0, "4.0"),
        p("Spare", "Chelsea", 0, "3.0"),
        p("Hurt", "Chelsea", 1, "9.0", status="i"),
    ]


def _chip_status_result(current_gw: int, tc=True, bb=True, fh=True) -> dict:
    def chip(avail):
        return {"available": avail, "used_in_gw": None if avail else 5}

    return {
        "current_gameweek": current_gw,
        "chips": {
            "triple_captain": chip(tc),
            "bench_boost": chip(bb),
            "free_hit": chip(fh),
        },
    }


async def _run_plan_chips(events, fixtures, chip_status):
    from server.tools import fpl as fpl_mod

    bootstrap = {
        "events": events,
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Chelsea", "short_name": "CHE"},
            {"id": 3, "name": "Liverpool", "short_name": "LIV"},
        ],
        "elements": [],
    }
    fpl_mod._bootstrap_cache = None
    with (
        respx.mock,
        patch(
            "server.tools.fpl.get_my_fpl_team",
            new=AsyncMock(return_value={"squad": _chip_squad()}),
        ),
        patch("server.tools.fpl.get_chip_status", new=AsyncMock(return_value=chip_status)),
    ):
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        respx.get(f"{_FPL_BASE}/fixtures/").mock(return_value=httpx.Response(200, json=fixtures))
        return await plan_chips()


def _fx(gw, h, a, hd=3, ad=3):
    return {"event": gw, "team_h": h, "team_a": a, "team_h_difficulty": hd, "team_a_difficulty": ad}


@pytest.mark.asyncio
async def test_plan_chips_ranks_double_gw_for_bench_boost_and_blank_for_free_hit():
    events = [{"id": gw, "finished": gw < 10} for gw in range(8, 13)]
    fixtures = [
        # GW10: Arsenal plays twice (bench player Benchy doubles), Chelsea blanks
        _fx(10, 1, 3),
        _fx(10, 3, 1),
        # GW11: Arsenal and Chelsea play once each
        _fx(11, 1, 2),
    ]
    result = await _run_plan_chips(events, fixtures, _chip_status_result(10))

    assert result["window"] == {"from": 10, "to": 19}
    bb = result["chips"]["bench_boost"]["best_gameweeks"]
    assert bb[0]["gameweek"] == 10
    fh = result["chips"]["free_hit"]["best_gameweeks"]
    # GW10: Chelsea blank -> injured Hurt is a non-benched starter with no fixture
    assert fh[0]["gameweek"] == 10 and fh[0]["score"] == 1
    gw10 = next(g for g in result["gameweeks"] if g["gameweek"] == 10)
    assert "Benchy" in gw10["double_gw_players"]
    assert "Hurt" in gw10["blank_gw_starters"]
    # GW12 has no fixtures yet, so it is not scored
    assert all(g["gameweek"] != 12 for g in result["gameweeks"])
    assert result["chips"]["triple_captain"]["must_use_by_gw"] == 19


@pytest.mark.asyncio
async def test_plan_chips_triple_captain_ignores_injured_and_picks_best_player():
    events = [{"id": 10, "finished": False}]
    fixtures = [_fx(10, 3, 2), _fx(10, 1, 2)]
    result = await _run_plan_chips(events, fixtures, _chip_status_result(10))

    gw = result["gameweeks"][0]
    # Hurt has the highest ppg but is injured, so Salah is the pick
    assert gw["triple_captain_pick"] == "Salah"


@pytest.mark.asyncio
async def test_plan_chips_second_half_window_and_used_chips():
    events = [{"id": gw, "finished": gw < 25} for gw in range(24, 30)]
    fixtures = [_fx(26, 1, 2)]
    status = _chip_status_result(25, tc=False)
    result = await _run_plan_chips(events, fixtures, status)

    assert result["window"] == {"from": 25, "to": 38}
    assert result["chips"]["triple_captain"] == {"available": False, "used_in_gw": 5}
    assert result["chips"]["bench_boost"]["must_use_by_gw"] == 38


@pytest.mark.asyncio
async def test_plan_chips_returns_error_when_no_team_id():
    with (
        patch(
            "server.tools.fpl.get_my_fpl_team",
            new=AsyncMock(return_value={"error": "FPL_TEAM_ID is not set in config."}),
        ),
        patch(
            "server.tools.fpl.get_chip_status",
            new=AsyncMock(return_value={"error": "FPL_TEAM_ID is not set in config."}),
        ),
    ):
        result = await plan_chips()

    assert "error" in result


def _price_player(pid, name, tin, tout, owned, **extra):
    return {
        "id": pid,
        "web_name": name,
        "first_name": name,
        "second_name": name,
        "team": 1,
        "element_type": 3,
        "now_cost": 85,
        "transfers_in_event": tin,
        "transfers_out_event": tout,
        "selected_by_percent": owned,
        "status": "a",
        **extra,
    }


async def _run_price_changes(elements, **kwargs):
    from server.tools import fpl as fpl_mod

    bootstrap = {
        "events": [],
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}],
        "elements": elements,
        "total_players": 10_000_000,
    }
    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        return await get_price_changes(**kwargs)


@pytest.mark.asyncio
async def test_get_price_changes_ranks_by_share_of_owners_and_skips_low_volume():
    elements = [
        # 100k net on 10% owners (1M) = 10%
        _price_player(1, "Big", 150_000, 50_000, "10.0"),
        # 100k net on 50% owners (5M) = 2%: same volume, smaller share, ranks lower
        _price_player(2, "Template", 120_000, 20_000, "50.0"),
        # 400k out on 20% owners (2M) = -20%
        _price_player(3, "Dumped", 0, 400_000, "20.0"),
        # Below the volume floor: ignored in rankings despite a huge share
        _price_player(4, "Tiny", 5_000, 0, "0.1"),
        # Unavailable players are ignored
        _price_player(5, "Gone", 900_000, 0, "5.0", status="u"),
    ]
    result = await _run_price_changes(elements)

    assert [p["name"] for p in result["likely_risers"]] == ["Big", "Template"]
    assert [p["name"] for p in result["likely_fallers"]] == ["Dumped"]
    assert result["likely_risers"][0]["net_pct_of_owners"] == 10.0
    assert result["likely_fallers"][0]["net_pct_of_owners"] == -20.0


@pytest.mark.asyncio
async def test_get_price_changes_direction_and_named_lookup():
    elements = [
        _price_player(1, "Big", 150_000, 50_000, "10.0", cost_change_event=1),
        _price_player(3, "Dumped", 0, 400_000, "20.0"),
    ]
    rise = await _run_price_changes(elements, direction="rise")
    assert "likely_fallers" not in rise

    named = await _run_price_changes(elements, player_names=["Big", "Nobody"])
    assert named["players"][0]["name"] == "Big"
    assert named["players"][0]["price_change_this_gw"] == 0.1
    assert named["not_found"] == ["Nobody"]


def _picks(starters, captain, bench=(), chip=None):
    """starters: 11 element ids; captain must be one of them."""
    picks = [
        {"element": e, "position": i + 1, "is_captain": e == captain, "is_vice_captain": False}
        for i, e in enumerate(starters)
    ]
    picks += [
        {"element": e, "position": 12 + i, "is_captain": False, "is_vice_captain": False}
        for i, e in enumerate(bench)
    ]
    return {"picks": picks, "active_chip": chip}


async def _run_mini_league(rival_picks, **kwargs):
    from server.tools import fpl as fpl_mod

    names = {i: f"P{i}" for i in range(1, 40)}
    bootstrap = {
        "events": [{"id": 9, "is_current": True, "is_next": False}],
        "teams": [],
        "elements": [{"id": i, "web_name": n} for i, n in names.items()],
    }
    standings = {
        "league": {"name": "Pals"},
        "standings": {
            "results": [
                {"entry": 100, "rank": 1, "player_name": "Ann", "entry_name": "A", "total": 500},
                {"entry": 1, "rank": 2, "player_name": "Me", "entry_name": "M", "total": 480},
                {"entry": 200, "rank": 3, "player_name": "Bob", "entry_name": "B", "total": 470},
                {"entry": 300, "rank": 9, "player_name": "Far", "entry_name": "F", "total": 300},
            ]
        },
    }
    mine = _picks(list(range(1, 12)), captain=1, bench=[12, 13, 14, 15])
    fpl_mod._bootstrap_cache = None
    with respx.mock:
        respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        respx.get(f"{_FPL_BASE}/leagues-classic/7/standings/").mock(
            return_value=httpx.Response(200, json=standings)
        )
        respx.get(f"{_FPL_BASE}/entry/1/event/9/picks/").mock(
            return_value=httpx.Response(200, json=mine)
        )
        for entry, picks in rival_picks.items():
            respx.get(f"{_FPL_BASE}/entry/{entry}/event/9/picks/").mock(
                return_value=picks
                if isinstance(picks, httpx.Response)
                else httpx.Response(200, json=picks)
            )
        return await analyse_mini_league(7, team_id_override=1, **kwargs)


@pytest.mark.asyncio
async def test_analyse_mini_league_finds_differentials_and_captain_overlap():
    ann = _picks([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20], captain=1, chip="3xc")  # same captain
    bob = _picks([2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 21], captain=20)
    result = await _run_mini_league({100: ann, 200: bob}, rival_count=2)

    assert result["league_name"] == "Pals"
    assert result["your_rank"] == 2
    assert [r["manager"] for r in result["rivals"]] == ["Ann", "Bob"]
    ann_r, bob_r = result["rivals"]
    assert ann_r["points_vs_you"] == 20 and bob_r["points_vs_you"] == -10
    assert ann_r["same_captain_as_you"] and not bob_r["same_captain_as_you"]
    assert ann_r["active_chip"] == "3xc"
    assert ann_r["their_differentials"] == ["P20"]
    assert ann_r["your_differentials"] == ["P11"]
    assert bob_r["captain"] == "P20"
    assert result["rivals_with_same_captain"] == 1
    # P20 is a starter for both rivals and not owned by me
    assert result["owned_by_most_rivals_not_you"] == ["P20"]
    assert result["your_unique_starters"] == ["P11"]


@pytest.mark.asyncio
async def test_analyse_mini_league_picks_nearest_rivals_and_reports_unavailable():
    ann = _picks(list(range(1, 12)), captain=1)
    # Bob (rank 3) is nearer than Far (rank 9); his picks 404 so he is listed unavailable
    result = await _run_mini_league({100: ann, 200: httpx.Response(404)}, rival_count=2)

    assert [r["manager"] for r in result["rivals"]] == ["Ann"]
    assert result["unavailable"] == ["Bob"]
    assert "Far" not in str(result)


@pytest.mark.asyncio
async def test_analyse_mini_league_requires_team_id():
    with patch("server.tools.fpl.settings") as mock_settings:
        mock_settings.fpl_team_id = None
        result = await analyse_mini_league(7)
    assert "error" in result
