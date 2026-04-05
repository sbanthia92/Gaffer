import httpx
import pytest
import respx

from server.tools.fpl import (
    TOOL_DEFINITIONS,
    get_fixtures,
    get_head_to_head,
    get_odds,
    get_player_recent_form,
    get_player_stats,
    get_player_vs_opponent,
    get_standings,
    get_team_all_fixtures,
    get_team_recent_fixtures,
    search_player,
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
async def test_search_player_returns_trimmed_response():
    respx.get(f"{_BASE}/players").mock(
        return_value=httpx.Response(
            200,
            json={"response": [{"player": {"id": 1100, "name": "Erling Haaland", "age": 24}}]},
        )
    )
    result = await search_player(name="Haaland")
    assert "players" in result
    assert result["players"][0]["id"] == 1100
    assert result["players"][0]["name"] == "Erling Haaland"


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


@respx.mock
@pytest.mark.asyncio
async def test_get_player_stats_returns_trimmed_response():
    respx.get(f"{_BASE}/players").mock(
        return_value=httpx.Response(
            200,
            json={
                "response": [
                    {
                        "player": {
                            "id": 276,
                            "name": "Erling Haaland",
                            "age": 24,
                            "nationality": "Norwegian",
                        },
                        "statistics": [
                            {
                                "team": {"name": "Man City"},
                                "games": {
                                    "position": "Attacker",
                                    "appearences": 28,
                                    "minutes": 2340,
                                    "rating": "8.5",
                                },
                                "goals": {"total": 22, "assists": 5},
                                "cards": {"yellow": 1, "red": 0},
                                "shots": {"on": 45},
                                "passes": {"key": 12},
                                "dribbles": {"success": 18},
                            }
                        ],
                    }
                ]
            },
        )
    )
    result = await get_player_stats(player_id=276)
    assert result["name"] == "Erling Haaland"
    assert result["goals"] == 22
    assert result["assists"] == 5
    assert result["team"] == "Man City"


@respx.mock
@pytest.mark.asyncio
async def test_get_player_recent_form_returns_per_game_stats():
    respx.get(f"{_BASE}/fixtures").mock(
        return_value=httpx.Response(200, json={"response": [_FIXTURE_ITEM]})
    )
    respx.get(f"{_BASE}/fixtures/players").mock(
        return_value=httpx.Response(200, json=_PLAYER_FIXTURE_STATS)
    )
    result = await get_player_recent_form(player_id=276, last_n=1)
    assert "recent_form" in result
    assert result["recent_form"][0]["goals"] == 1
    assert result["recent_form"][0]["minutes"] == 90


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


@respx.mock
@pytest.mark.asyncio
async def test_get_player_vs_opponent_returns_per_game_stats():
    respx.get(f"{_BASE}/fixtures/headtohead").mock(
        return_value=httpx.Response(200, json={"response": [_FIXTURE_ITEM]})
    )
    respx.get(f"{_BASE}/fixtures/players").mock(
        return_value=httpx.Response(200, json=_PLAYER_FIXTURE_STATS)
    )
    result = await get_player_vs_opponent(player_id=276, team1_id=50, team2_id=49, last_n=5)
    assert "player_vs_opponent" in result
    assert result["player_vs_opponent"][0]["goals"] == 1
    assert result["player_vs_opponent"][0]["minutes"] == 90


@respx.mock
@pytest.mark.asyncio
async def test_api_error_raises():
    respx.get(f"{_BASE}/fixtures").mock(return_value=httpx.Response(401))
    with pytest.raises(httpx.HTTPStatusError):
        await get_fixtures()


def test_tool_definitions_structure():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert names == {
        "search_player",
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
    }
    for tool in TOOL_DEFINITIONS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
