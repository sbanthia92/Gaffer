"""
FPL MCP tools — live data via API-Sports.

Each public function fetches data from the API-Sports football API and returns
a trimmed summary dict. Raw API responses are never passed to Claude directly —
they are too large and blow through token limits.

API-Sports docs: https://www.api-football.com/documentation-v3
Premier League ID: 39
"""

import httpx

from server.config import settings

_BASE_URL = "https://v3.football.api-sports.io"
_PREMIER_LEAGUE_ID = 39
_CURRENT_SEASON = "2025"  # 2025-26 season


def _headers() -> dict[str, str]:
    return {"x-apisports-key": settings.api_sports_key}


async def search_player(name: str) -> dict:
    """Search for a player by name and return their ID and basic info."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        response = await client.get(
            "/players",
            params={
                "search": name,
                "league": _PREMIER_LEAGUE_ID,
                "season": _CURRENT_SEASON,
            },
        )
        response.raise_for_status()
        data = response.json()

    players = []
    for item in data.get("response", [])[:5]:
        p = item.get("player", {})
        players.append({"id": p.get("id"), "name": p.get("name"), "age": p.get("age")})
    return {"players": players}


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
        data = response.json()

    fixtures = []
    for item in data.get("response", []):
        f = item.get("fixture", {})
        teams = item.get("teams", {})
        fixtures.append(
            {
                "fixture_id": f.get("id"),
                "date": f.get("date"),
                "home": teams.get("home", {}).get("name"),
                "away": teams.get("away", {}).get("name"),
                "venue": f.get("venue", {}).get("name"),
            }
        )
    return {"fixtures": fixtures}


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
        data = response.json()

    standings = []
    try:
        table = data["response"][0]["league"]["standings"][0]
        for entry in table:
            standings.append(
                {
                    "rank": entry.get("rank"),
                    "team": entry.get("team", {}).get("name"),
                    "played": entry.get("all", {}).get("played"),
                    "won": entry.get("all", {}).get("win"),
                    "drawn": entry.get("all", {}).get("draw"),
                    "lost": entry.get("all", {}).get("lose"),
                    "goals_for": entry.get("all", {}).get("goals", {}).get("for"),
                    "goals_against": entry.get("all", {}).get("goals", {}).get("against"),
                    "points": entry.get("points"),
                    "form": entry.get("form"),
                }
            )
    except (IndexError, KeyError):
        pass
    return {"standings": standings}


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
        data = response.json()

    try:
        item = data["response"][0]
        p = item["player"]
        s = item["statistics"][0]
        return {
            "name": p.get("name"),
            "age": p.get("age"),
            "nationality": p.get("nationality"),
            "team": s.get("team", {}).get("name"),
            "position": s.get("games", {}).get("position"),
            "appearances": s.get("games", {}).get("appearences"),
            "minutes": s.get("games", {}).get("minutes"),
            "goals": s.get("goals", {}).get("total"),
            "assists": s.get("goals", {}).get("assists"),
            "yellow_cards": s.get("cards", {}).get("yellow"),
            "red_cards": s.get("cards", {}).get("red"),
            "shots_on_target": s.get("shots", {}).get("on"),
            "key_passes": s.get("passes", {}).get("key"),
            "dribbles_success": s.get("dribbles", {}).get("success"),
            "rating": s.get("games", {}).get("rating"),
        }
    except (IndexError, KeyError):
        return {"error": "Player stats not found"}


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
        data = response.json()

    fixtures = []
    for item in data.get("response", []):
        f = item.get("fixture", {})
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        fixtures.append(
            {
                "date": f.get("date"),
                "home": teams.get("home", {}).get("name"),
                "away": teams.get("away", {}).get("name"),
                "home_goals": goals.get("home"),
                "away_goals": goals.get("away"),
            }
        )
    return {"recent_fixtures": fixtures}


async def get_odds(fixture_id: int) -> dict:
    """Fetch current odds for a fixture."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        response = await client.get(
            "/odds",
            params={"fixture": fixture_id},
        )
        response.raise_for_status()
        data = response.json()

    try:
        bookmaker = data["response"][0]["bookmakers"][0]
        bets = {}
        for bet in bookmaker.get("bets", [])[:3]:
            bets[bet["name"]] = {v["value"]: v["odd"] for v in bet.get("values", [])}
        return {"fixture_id": fixture_id, "bookmaker": bookmaker.get("name"), "bets": bets}
    except (IndexError, KeyError):
        return {"fixture_id": fixture_id, "odds": "unavailable"}


# Tool definitions in Anthropic tool-use format.
# Claude receives these and decides which to call based on the question.
TOOL_DEFINITIONS = [
    {
        "name": "search_player",
        "description": (
            "Search for a Premier League player by name to get their player ID. "
            "Always call this first when you need stats or recent fixtures for a specific player."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Player name to search for, e.g. 'Haaland' or 'Salah'.",
                }
            },
            "required": ["name"],
        },
    },
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
