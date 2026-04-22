from unittest.mock import patch

import httpx
import pytest
import respx

from server.tools.fpl import (
    TOOL_DEFINITIONS,
    get_fixtures,
    get_gameweek_schedule,
    get_head_to_head,
    get_my_fpl_team,
    get_odds,
    get_player_recent_form,
    get_player_stats,
    get_player_vs_opponent,
    get_standings,
    get_team_all_fixtures,
    get_team_recent_fixtures,
    search_players_by_criteria,
    search_team,
)

_BASE = "https://v3.football.api-sports.io"

_FIXTURE_ITEM = {
    "fixture": {"id": 42, "date": "2026-03-30T15:00:00+00:00"},
    "teams": {
        "home": {"name": "Man City", "winner": True},
        "away": {"name": "Chelsea", "winner": False},
    },
    "goals": {"home": 2, "away": 1},
}

_PLAYER_FIXTURE_STATS = {
    "response": [
        {
            "players": [
                {
                    "player": {"id": 276},
                    "statistics": [
                        {
                            "games": {"minutes": 90, "rating": "8.2"},
                            "goals": {"total": 1, "assists": 0},
                            "shots": {"on": 3},
                        }
                    ],
                }
            ]
        }
    ]
}


@respx.mock
@pytest.mark.asyncio
async def test_search_team_returns_trimmed_response():
    respx.get(f"{_BASE}/teams").mock(
        return_value=httpx.Response(
            200,
            json={"response": [{"team": {"id": 49, "name": "Chelsea"}}]},
        )
    )
    result = await search_team(name="Chelsea")
    assert "teams" in result
    assert result["teams"][0]["id"] == 49
    assert result["teams"][0]["name"] == "Chelsea"


@respx.mock
@pytest.mark.asyncio
async def test_get_fixtures_returns_trimmed_response():
    respx.get(f"{_BASE}/fixtures").mock(
        return_value=httpx.Response(
            200,
            json={
                "response": [
                    {
                        "fixture": {"id": 1, "date": "2026-04-10", "venue": {"name": "Anfield"}},
                        "teams": {
                            "home": {"name": "Liverpool"},
                            "away": {"name": "Man City"},
                        },
                    }
                ]
            },
        )
    )
    result = await get_fixtures(next_n=5)
    assert "fixtures" in result
    assert result["fixtures"][0]["fixture_id"] == 1
    assert result["fixtures"][0]["home"] == "Liverpool"
    assert result["fixtures"][0]["away"] == "Man City"


@respx.mock
@pytest.mark.asyncio
async def test_get_standings_returns_trimmed_response():
    respx.get(f"{_BASE}/standings").mock(
        return_value=httpx.Response(
            200,
            json={
                "response": [
                    {
                        "league": {
                            "standings": [
                                [
                                    {
                                        "rank": 1,
                                        "team": {"name": "Arsenal"},
                                        "points": 70,
                                        "form": "WWWDW",
                                        "all": {
                                            "played": 32,
                                            "win": 22,
                                            "draw": 4,
                                            "lose": 6,
                                            "goals": {"for": 65, "against": 28},
                                        },
                                    }
                                ]
                            ]
                        }
                    }
                ]
            },
        )
    )
    result = await get_standings()
    assert "standings" in result
    assert result["standings"][0]["rank"] == 1
    assert result["standings"][0]["team"] == "Arsenal"
    assert result["standings"][0]["points"] == 70


@pytest.mark.asyncio
async def test_get_player_stats_returns_fpl_data():
    _FPL = "https://fantasy.premierleague.com/api"
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
        respx.get(f"{_FPL}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        with patch("server.tools.db.execute", new=AsyncMock(return_value=db_result)):
            result = await get_player_stats(player_name="Haaland")

    assert "player_stats" in result
    assert result["player_stats"]["goals_scored"] == 22
    assert result["player_stats"]["team"] == "Man City"
    assert result["player_stats"]["total_points"] == 180


@respx.mock
@pytest.mark.asyncio
async def test_get_player_recent_form_returns_per_game_stats():
    _FPL = "https://fantasy.premierleague.com/api"
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
    respx.get(f"{_FPL}/bootstrap-static/").mock(return_value=httpx.Response(200, json=bootstrap))
    respx.get(f"{_FPL}/element-summary/328/").mock(
        return_value=httpx.Response(200, json=element_summary)
    )
    result = await get_player_recent_form(player_name="Haaland", last_n=1)
    assert "recent_form" in result
    assert result["recent_form"][0]["goals"] == 2
    assert result["recent_form"][0]["minutes"] == 90
    assert result["recent_form"][0]["total_points"] == 14
    assert result["recent_form"][0]["bonus"] == 3
    assert result["player"] == "Erling Haaland"


@respx.mock
@pytest.mark.asyncio
async def test_get_team_recent_fixtures_returns_trimmed_response():
    respx.get(f"{_BASE}/fixtures").mock(
        return_value=httpx.Response(200, json={"response": [_FIXTURE_ITEM]})
    )
    result = await get_team_recent_fixtures(team_id=50, last_n=5)
    assert "recent_fixtures" in result
    assert result["recent_fixtures"][0]["home"] == "Man City"
    assert result["recent_fixtures"][0]["home_goals"] == 2


@respx.mock
@pytest.mark.asyncio
async def test_get_head_to_head_returns_trimmed_response():
    respx.get(f"{_BASE}/fixtures/headtohead").mock(
        return_value=httpx.Response(200, json={"response": [_FIXTURE_ITEM]})
    )
    result = await get_head_to_head(team1_id=50, team2_id=49, last_n=5)
    assert "h2h" in result
    assert result["h2h"][0]["home"] == "Man City"
    assert result["h2h"][0]["away"] == "Chelsea"


@respx.mock
@pytest.mark.asyncio
async def test_get_odds_returns_trimmed_response():
    respx.get(f"{_BASE}/odds").mock(
        return_value=httpx.Response(
            200,
            json={
                "response": [
                    {
                        "bookmakers": [
                            {
                                "name": "Bet365",
                                "bets": [
                                    {
                                        "name": "Match Winner",
                                        "values": [
                                            {"value": "Home", "odd": "1.80"},
                                            {"value": "Draw", "odd": "3.50"},
                                            {"value": "Away", "odd": "4.20"},
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ]
            },
        )
    )
    result = await get_odds(fixture_id=999)
    assert result["fixture_id"] == 999
    assert result["bookmaker"] == "Bet365"
    assert "Match Winner" in result["bets"]


@respx.mock
@pytest.mark.asyncio
async def test_get_team_all_fixtures_returns_all_competitions():
    respx.get(f"{_BASE}/fixtures").mock(
        return_value=httpx.Response(
            200,
            json={
                "response": [
                    {
                        "fixture": {
                            "id": 99,
                            "date": "2026-04-15T20:00:00+00:00",
                            "venue": {"name": "Etihad"},
                        },
                        "league": {"name": "UEFA Champions League", "round": "QF"},
                        "teams": {
                            "home": {"name": "Man City"},
                            "away": {"name": "Real Madrid"},
                        },
                    }
                ]
            },
        )
    )
    result = await get_team_all_fixtures(team_id=50, next_n=7)
    assert "all_fixtures" in result
    assert result["all_fixtures"][0]["competition"] == "UEFA Champions League"
    assert result["all_fixtures"][0]["away"] == "Real Madrid"


@pytest.mark.asyncio
async def test_get_player_vs_opponent_returns_per_game_stats():
    _FPL = "https://fantasy.premierleague.com/api"
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
        respx.get(f"{_FPL}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        with patch("server.tools.db.execute", new=AsyncMock(return_value=db_result)):
            result = await get_player_vs_opponent(
                player_name="Haaland", opponent_name="Chelsea", last_n=5
            )

    assert result["player"] == "Erling Haaland"
    assert result["opponent"] == "Chelsea"
    assert result["games"][0]["goals_scored"] == 2
    assert result["games"][0]["total_points"] == 15
    assert result["games"][0]["minutes"] == 90


_FPL_BASE = "https://fantasy.premierleague.com/api"

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


@respx.mock
@pytest.mark.asyncio
async def test_get_my_fpl_team_returns_squad():
    from server.tools import fpl as fpl_mod

    fpl_mod._bootstrap_cache = None
    respx.get(f"{_FPL_BASE}/bootstrap-static/").mock(
        return_value=httpx.Response(200, json=_BOOTSTRAP)
    )
    respx.get(f"{_FPL_BASE}/entry/123/event/36/picks/").mock(
        return_value=httpx.Response(200, json=_PICKS)
    )
    with patch("server.tools.fpl.settings") as mock_settings:
        mock_settings.fpl_team_id = 123
        mock_settings.api_sports_key = "test-key"
        result = await get_my_fpl_team()
    assert result["gameweek"] == 36
    assert result["squad"][0]["name"] == "Erling Haaland"
    assert result["squad"][0]["is_captain"] is True
    assert result["squad"][0]["selling_price"] == 14.0


@respx.mock
@pytest.mark.asyncio
async def test_get_my_fpl_team_no_team_id():
    with patch("server.tools.fpl.settings") as mock_settings:
        mock_settings.fpl_team_id = None
        result = await get_my_fpl_team()
    assert "error" in result


@respx.mock
@pytest.mark.asyncio
async def test_api_error_raises():
    respx.get(f"{_BASE}/fixtures").mock(return_value=httpx.Response(401))
    with pytest.raises(httpx.HTTPStatusError):
        await get_fixtures()


@pytest.mark.asyncio
async def test_search_players_by_criteria_sorts_by_form_and_includes_defensive_stats():
    _FPL = "https://fantasy.premierleague.com/api"
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
        respx.get(f"{_FPL}/bootstrap-static/").mock(
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
    _FPL = "https://fantasy.premierleague.com/api"
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
        respx.get(f"{_FPL}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        result = await search_players_by_criteria(position="FWD")

    # PlayerB has lower total_points but higher form — should rank first
    assert result["players"][0]["name"] == "PlayerB"
    assert result["players"][1]["name"] == "PlayerA"


@pytest.mark.asyncio
async def test_get_gameweek_schedule_includes_difficulty_and_skips_unscheduled_blanks():
    _FPL = "https://fantasy.premierleague.com/api"
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
        respx.get(f"{_FPL}/bootstrap-static/").mock(
            return_value=httpx.Response(200, json=bootstrap)
        )
        respx.get(f"{_FPL}/fixtures/").mock(return_value=httpx.Response(200, json=fixtures))
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


def test_tool_definitions_structure():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert names == {
        "get_my_fpl_team",
        "get_chip_status",
        "get_gameweek_schedule",
        "search_team",
        "get_fixtures",
        "get_standings",
        "get_player_stats",
        "get_player_recent_form",
        "get_team_recent_fixtures",
        "get_team_all_fixtures",
        "get_head_to_head",
        "get_player_vs_opponent",
        "get_odds",
        "search_players_by_criteria",
    }
    for tool in TOOL_DEFINITIONS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
