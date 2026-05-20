from unittest.mock import patch

import httpx
import pytest
import respx

from server.tools.fpl import (
    TOOL_DEFINITIONS,
    get_captain_options,
    get_fixtures,
    get_gameweek_schedule,
    get_head_to_head,
    get_mini_league_standings,
    get_my_fpl_team,
    get_player_recent_form,
    get_player_stats,
    get_player_vs_opponent,
    get_standings,
    get_team_all_fixtures,
    get_team_recent_fixtures,
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


def test_tool_definitions_structure():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert names == {
        "get_my_fpl_team",
        "get_chip_status",
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
