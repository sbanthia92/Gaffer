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


async def get_player_recent_form(player_id: int, last_n: int = 5) -> dict:
    """
    Fetch a player's recent form — goals, assists, minutes, and rating per game.
    Uses /fixtures/players to get individual stats per match.
    """
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        # Step 1: get the last N fixture IDs the player appeared in
        fix_resp = await client.get(
            "/fixtures",
            params={
                "league": _PREMIER_LEAGUE_ID,
                "season": _CURRENT_SEASON,
                "last": last_n,
                "player": player_id,
            },
        )
        fix_resp.raise_for_status()
        fixture_data = fix_resp.json()

        fixture_ids = [item["fixture"]["id"] for item in fixture_data.get("response", [])]

        # Step 2: for each fixture, fetch individual player stats
        games = []
        for fid in fixture_ids:
            pr = await client.get("/fixtures/players", params={"fixture": fid})
            if pr.status_code != 200:
                continue
            pr_data = pr.json()
            for team in pr_data.get("response", []):
                for player in team.get("players", []):
                    if player.get("player", {}).get("id") == player_id:
                        s = player.get("statistics", [{}])[0]
                        fix_meta = fixture_data["response"]
                        meta = next((f for f in fix_meta if f["fixture"]["id"] == fid), {})
                        teams = meta.get("teams", {})
                        games.append(
                            {
                                "fixture_id": fid,
                                "date": meta.get("fixture", {}).get("date", "")[:10],
                                "home": teams.get("home", {}).get("name"),
                                "away": teams.get("away", {}).get("name"),
                                "result": (
                                    f"{meta.get('goals', {}).get('home')}-"
                                    f"{meta.get('goals', {}).get('away')}"
                                ),
                                "minutes": s.get("games", {}).get("minutes"),
                                "goals": s.get("goals", {}).get("total") or 0,
                                "assists": s.get("goals", {}).get("assists") or 0,
                                "shots_on": s.get("shots", {}).get("on") or 0,
                                "rating": s.get("games", {}).get("rating"),
                            }
                        )
    return {"recent_form": games}


async def search_team(name: str) -> dict:
    """Search for a Premier League team by name to get their team ID."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        response = await client.get(
            "/teams",
            params={
                "search": name,
                "league": _PREMIER_LEAGUE_ID,
                "season": _CURRENT_SEASON,
            },
        )
        response.raise_for_status()
        data = response.json()

    teams = []
    for item in data.get("response", [])[:5]:
        t = item.get("team", {})
        teams.append({"id": t.get("id"), "name": t.get("name")})
    return {"teams": teams}


async def get_team_recent_fixtures(team_id: int, last_n: int = 5) -> dict:
    """Fetch a team's last N results in the Premier League."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        response = await client.get(
            "/fixtures",
            params={
                "league": _PREMIER_LEAGUE_ID,
                "season": _CURRENT_SEASON,
                "last": last_n,
                "team": team_id,
            },
        )
        response.raise_for_status()
        data = response.json()

    fixtures = []
    for item in data.get("response", []):
        f = item.get("fixture", {})
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        home = teams.get("home", {})
        away = teams.get("away", {})
        fixtures.append(
            {
                "date": f.get("date", "")[:10],
                "home": home.get("name"),
                "away": away.get("name"),
                "home_goals": goals.get("home"),
                "away_goals": goals.get("away"),
                "home_winner": home.get("winner"),
                "away_winner": away.get("winner"),
            }
        )
    return {"recent_fixtures": fixtures}


async def get_head_to_head(team1_id: int, team2_id: int, last_n: int = 5) -> dict:
    """Fetch head-to-head results between two teams."""
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        response = await client.get(
            "/fixtures/headtohead",
            params={
                "h2h": f"{team1_id}-{team2_id}",
                "last": last_n,
            },
        )
        response.raise_for_status()
        data = response.json()

    fixtures = []
    for item in data.get("response", []):
        f = item.get("fixture", {})
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        home = teams.get("home", {})
        away = teams.get("away", {})
        fixtures.append(
            {
                "date": f.get("date", "")[:10],
                "home": home.get("name"),
                "away": away.get("name"),
                "home_goals": goals.get("home"),
                "away_goals": goals.get("away"),
                "home_winner": home.get("winner"),
                "away_winner": away.get("winner"),
            }
        )
    return {"h2h": fixtures}


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
        "name": "get_player_recent_form",
        "description": (
            "Get a player's recent form — goals, assists, minutes, and rating per game. "
            "Use this to assess whether a player is in form for captaincy or transfer decisions."
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
                    "description": "Number of recent games to return. Defaults to 5.",
                    "default": 5,
                },
            },
            "required": ["player_id"],
        },
    },
    {
        "name": "search_team",
        "description": (
            "Search for a Premier League team by name to get their team ID. "
            "Call this before get_team_recent_fixtures or get_head_to_head."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Team name to search for, e.g. 'Chelsea' or 'Arsenal'.",
                }
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_team_recent_fixtures",
        "description": (
            "Get a team's last N Premier League results. "
            "Use this for opponent form analysis — not just the player's team."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id": {
                    "type": "integer",
                    "description": "The API-Sports team ID.",
                },
                "last_n": {
                    "type": "integer",
                    "description": "Number of recent fixtures to return. Defaults to 5.",
                    "default": 5,
                },
            },
            "required": ["team_id"],
        },
    },
    {
        "name": "get_head_to_head",
        "description": (
            "Get head-to-head results between two teams. "
            "Use this for historical matchup context between the player's team and their opponent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "team1_id": {
                    "type": "integer",
                    "description": "The API-Sports team ID for the first team.",
                },
                "team2_id": {
                    "type": "integer",
                    "description": "The API-Sports team ID for the second team.",
                },
                "last_n": {
                    "type": "integer",
                    "description": "Number of recent h2h fixtures to return. Defaults to 5.",
                    "default": 5,
                },
            },
            "required": ["team1_id", "team2_id"],
        },
    },
]
