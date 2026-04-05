import httpx
import pytest
import respx

from server.tools.fpl import (
    TOOL_DEFINITIONS,
    get_fixtures,
    get_odds,
    get_player_recent_fixtures,
    get_player_stats,
    get_standings,
)

_BASE = "https://v3.football.api-sports.io"


@respx.mock
@pytest.mark.asyncio
async def test_get_fixtures_returns_response():
    respx.get(f"{_BASE}/fixtures").mock(
        return_value=httpx.Response(200, json={"response": [{"fixture": {"id": 1}}]})
    )
    result = await get_fixtures(next_n=5)
    assert result["response"][0]["fixture"]["id"] == 1


@respx.mock
@pytest.mark.asyncio
async def test_get_standings_returns_response():
    respx.get(f"{_BASE}/standings").mock(
        return_value=httpx.Response(200, json={"response": [{"league": {"standings": []}}]})
    )
    result = await get_standings()
    assert "response" in result


@respx.mock
@pytest.mark.asyncio
async def test_get_player_stats_returns_response():
    respx.get(f"{_BASE}/players").mock(
        return_value=httpx.Response(
            200,
            json={"response": [{"player": {"id": 276, "name": "Erling Haaland"}}]},
        )
    )
    result = await get_player_stats(player_id=276)
    assert result["response"][0]["player"]["name"] == "Erling Haaland"


@respx.mock
@pytest.mark.asyncio
async def test_get_odds_returns_response():
    respx.get(f"{_BASE}/odds").mock(
        return_value=httpx.Response(200, json={"response": [{"fixture": {"id": 999}}]})
    )
    result = await get_odds(fixture_id=999)
    assert result["response"][0]["fixture"]["id"] == 999


@respx.mock
@pytest.mark.asyncio
async def test_get_player_recent_fixtures_returns_response():
    respx.get(f"{_BASE}/fixtures").mock(
        return_value=httpx.Response(200, json={"response": [{"fixture": {"id": 42}}]})
    )
    result = await get_player_recent_fixtures(player_id=276, last_n=5)
    assert result["response"][0]["fixture"]["id"] == 42


@respx.mock
@pytest.mark.asyncio
async def test_api_error_raises():
    respx.get(f"{_BASE}/fixtures").mock(return_value=httpx.Response(401))
    with pytest.raises(httpx.HTTPStatusError):
        await get_fixtures()


def test_tool_definitions_structure():
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert names == {
        "get_fixtures",
        "get_standings",
        "get_player_stats",
        "get_odds",
        "get_player_recent_fixtures",
    }
    for tool in TOOL_DEFINITIONS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
