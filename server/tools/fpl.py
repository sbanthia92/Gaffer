"""
FPL MCP tools — live data via API-Sports.

Each public function fetches one data type from the API-Sports football API.
The TOOL_DEFINITIONS list exposes them to Claude as callable tools.

API-Sports docs: https://www.api-football.com/documentation-v3
Premier League ID: 39
"""

import httpx

from server.config import settings

_BASE_URL = "https://v3.football.api-sports.io"
_PREMIER_LEAGUE_ID = 39
_CURRENT_SEASON = "2024"  # 2024-25 season


def _headers() -> dict[str, str]:
    return {"x-apisports-key": settings.api_sports_key}


async def get_fixtures(next_n: int = 10) -> dict:
    """Fetch the next N Premier League fixtures."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        response = await client.get(
            "/fixtures",
            params={
                "league": _PREMIER_LEAGUE_ID,
                "season": _CURRENT_SEASON,
                "next": next_n,
            },
        )
        response.raise_for_status()
        return response.json()


async def get_standings() -> dict:
    """Fetch current Premier League standings."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        response = await client.get(
            "/standings",
            params={
                "league": _PREMIER_LEAGUE_ID,
                "season": _CURRENT_SEASON,
            },
        )
        response.raise_for_status()
        return response.json()


async def get_player_stats(player_id: int) -> dict:
    """Fetch season stats for a player in the Premier League."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        response = await client.get(
            "/players",
            params={
                "id": player_id,
                "league": _PREMIER_LEAGUE_ID,
                "season": _CURRENT_SEASON,
            },
        )
        response.raise_for_status()
        return response.json()


async def get_odds(fixture_id: int) -> dict:
    """Fetch current odds for a fixture."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        response = await client.get(
            "/odds",
            params={"fixture": fixture_id},
        )
        response.raise_for_status()
        return response.json()


async def get_player_recent_fixtures(player_id: int, last_n: int = 10) -> dict:
    """Fetch a player's last N fixtures in the Premier League."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        response = await client.get(
            "/fixtures",
            params={
                "league": _PREMIER_LEAGUE_ID,
                "season": _CURRENT_SEASON,
                "last": last_n,
                "player": player_id,
            },
        )
        response.raise_for_status()
        return response.json()


# Tool definitions in Anthropic tool-use format.
# Claude receives these and decides which to call based on the question.
TOOL_DEFINITIONS = [
    {
        "name": "get_fixtures",
        "description": (
            "Get upcoming Premier League fixtures. "
            "Use this to find who teams are playing next, fixture difficulty, "
            "and schedule context for transfer or captain decisions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "next_n": {
                    "type": "integer",
                    "description": "Number of upcoming fixtures to return. Defaults to 10.",
                    "default": 10,
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_standings",
        "description": (
            "Get current Premier League standings. "
            "Use this for context on team form, position, and motivation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_player_stats",
        "description": (
            "Get season statistics for a Premier League player — goals, assists, "
            "minutes played, cards, and more. Use this for captain or transfer decisions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "integer",
                    "description": "The API-Sports player ID.",
                }
            },
            "required": ["player_id"],
        },
    },
    {
        "name": "get_odds",
        "description": (
            "Get current bookmaker odds for a fixture. "
            "Use this to gauge match outcome probability and expected goal context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fixture_id": {
                    "type": "integer",
                    "description": "The API-Sports fixture ID.",
                }
            },
            "required": ["fixture_id"],
        },
    },
    {
        "name": "get_player_recent_fixtures",
        "description": (
            "Get a player's last N fixtures in the Premier League. "
            "Use this to assess recent form — goals, assists, and minutes in recent games."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "integer",
                    "description": "The API-Sports player ID.",
                },
                "last_n": {
                    "type": "integer",
                    "description": "Number of recent fixtures to return. Defaults to 10.",
                    "default": 10,
                },
            },
            "required": ["player_id"],
        },
    },
]
