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
_FPL_BASE_URL = "https://fantasy.premierleague.com/api"
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
            params={"search": name},
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


async def get_team_all_fixtures(team_id: int, next_n: int = 7) -> dict:
    """
    Fetch a team's next N fixtures across ALL competitions — PL, UCL, FA Cup etc.
    Use this to assess fixture congestion and rotation risk.
    """
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        response = await client.get(
            "/fixtures",
            params={
                "team": team_id,
                "next": next_n,
                "season": _CURRENT_SEASON,
            },
        )
        response.raise_for_status()
        data = response.json()

    fixtures = []
    for item in data.get("response", []):
        f = item.get("fixture", {})
        teams = item.get("teams", {})
        league = item.get("league", {})
        fixtures.append(
            {
                "date": f.get("date", "")[:10],
                "competition": league.get("name"),
                "round": league.get("round"),
                "home": teams.get("home", {}).get("name"),
                "away": teams.get("away", {}).get("name"),
                "venue": f.get("venue", {}).get("name"),
            }
        )
    return {"all_fixtures": fixtures}


async def get_player_vs_opponent(
    player_id: int, team1_id: int, team2_id: int, last_n: int = 5
) -> dict:
    """
    Fetch a player's individual stats in past h2h games between their team and the opponent.
    Returns goals, assists, minutes and rating per match.
    """
    async with httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0) as client:
        # Step 1: get h2h fixture IDs
        h2h_resp = await client.get(
            "/fixtures/headtohead",
            params={"h2h": f"{team1_id}-{team2_id}", "last": last_n},
        )
        h2h_resp.raise_for_status()
        h2h_data = h2h_resp.json()
        fixture_items = h2h_data.get("response", [])
        fixture_ids = [item["fixture"]["id"] for item in fixture_items]

        # Step 2: fetch player stats for each fixture
        games = []
        for fid in fixture_ids:
            pr = await client.get("/fixtures/players", params={"fixture": fid})
            if pr.status_code != 200:
                continue
            for team in pr.json().get("response", []):
                for player in team.get("players", []):
                    if player.get("player", {}).get("id") == player_id:
                        s = player.get("statistics", [{}])[0]
                        meta = next((f for f in fixture_items if f["fixture"]["id"] == fid), {})
                        teams = meta.get("teams", {})
                        goals_data = meta.get("goals", {})
                        games.append(
                            {
                                "date": meta.get("fixture", {}).get("date", "")[:10],
                                "home": teams.get("home", {}).get("name"),
                                "away": teams.get("away", {}).get("name"),
                                "result": (f"{goals_data.get('home')}-{goals_data.get('away')}"),
                                "minutes": s.get("games", {}).get("minutes"),
                                "goals": s.get("goals", {}).get("total") or 0,
                                "assists": s.get("goals", {}).get("assists") or 0,
                                "shots_on": s.get("shots", {}).get("on") or 0,
                                "rating": s.get("games", {}).get("rating"),
                            }
                        )
    return {"player_vs_opponent": games}


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


async def get_my_fpl_team(team_id_override: int | None = None) -> dict:
    """
    Fetch the user's current FPL squad and active chip from the official FPL API.
    Returns player names, positions, selling price, and captain/vice-captain picks.
    team_id_override takes precedence over the FPL_TEAM_ID env var.
    """
    team_id = team_id_override or settings.fpl_team_id
    if not team_id:
        return {"error": "FPL_TEAM_ID is not set in config."}

    async with httpx.AsyncClient(base_url=_FPL_BASE_URL, timeout=10.0) as client:
        # Fetch bootstrap to get current gameweek and player name mapping
        bootstrap = await client.get("/bootstrap-static/")
        bootstrap.raise_for_status()
        bootstrap_data = bootstrap.json()

        # Find the current gameweek
        current_gw = next(
            (e["id"] for e in bootstrap_data["events"] if e["is_current"]),
            None,
        )
        if not current_gw:
            # Fall back to next gameweek if between gameweeks
            current_gw = next(
                (e["id"] for e in bootstrap_data["events"] if e["is_next"]),
                1,
            )

        # Build player ID → name/team/position map
        position_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
        team_map = {t["id"]: t["name"] for t in bootstrap_data["teams"]}
        player_map = {
            p["id"]: {
                "name": f"{p['first_name']} {p['second_name']}",
                "team": team_map.get(p["team"], ""),
                "position": position_map.get(p["element_type"], ""),
            }
            for p in bootstrap_data["elements"]
        }

        # Fetch the team's picks for the current gameweek
        picks_resp = await client.get(f"/entry/{team_id}/event/{current_gw}/picks/")
        picks_resp.raise_for_status()
        picks_data = picks_resp.json()

    squad = []
    for pick in picks_data.get("picks", []):
        pid = pick["element"]
        info = player_map.get(pid, {})
        squad.append(
            {
                "name": info.get("name"),
                "team": info.get("team"),
                "position": info.get("position"),
                "selling_price": pick.get("selling_price", 0) / 10,
                "multiplier": pick.get("multiplier"),  # 2 = captain, 3 = TC, 0 = benched
                "is_captain": pick.get("is_captain"),
                "is_vice_captain": pick.get("is_vice_captain"),
            }
        )

    active_chip = picks_data.get("active_chip")
    return {
        "gameweek": current_gw,
        "active_chip": active_chip,
        "squad": squad,
    }


_POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
_POSITION_IDS = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}

# ── Bootstrap cache (prices/positions from live FPL API) ──────────────────────
import time as _time  # noqa: E402

_bootstrap_cache: dict | None = None
_bootstrap_ts: float = 0
_BOOTSTRAP_TTL = 3600  # 1 hour


async def _get_bootstrap() -> dict:
    global _bootstrap_cache, _bootstrap_ts
    if _bootstrap_cache is None or _time.monotonic() - _bootstrap_ts > _BOOTSTRAP_TTL:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{_FPL_BASE_URL}/bootstrap-static/")
            r.raise_for_status()
            _bootstrap_cache = r.json()
            _bootstrap_ts = _time.monotonic()
    return _bootstrap_cache


async def search_players_by_criteria(
    position: str | None = None,
    max_price: float | None = None,
    min_price: float | None = None,
    top_n: int = 10,
) -> dict:
    """Search FPL players by position and/or price using live FPL data."""
    data = await _get_bootstrap()
    elements = data.get("elements", [])
    teams = {t["id"]: t["short_name"] for t in data.get("teams", [])}

    results = []
    for p in elements:
        price = p["now_cost"] / 10
        pos_id = p.get("element_type")

        if position and _POSITION_IDS.get(position.upper()) != pos_id:
            continue
        if max_price is not None and price > max_price:
            continue
        if min_price is not None and price < min_price:
            continue

        results.append(
            {
                "name": p["web_name"],
                "team": teams.get(p["team"], ""),
                "position": _POSITION_MAP.get(pos_id, ""),
                "price": price,
                "total_points": p.get("total_points", 0),
                "form": p.get("form", "0.0"),
                "selected_by_percent": p.get("selected_by_percent", "0.0"),
                "goals_scored": p.get("goals_scored", 0),
                "assists": p.get("assists", 0),
                "minutes": p.get("minutes", 0),
            }
        )

    # Sort by total points descending, return top N
    results.sort(key=lambda x: x["total_points"], reverse=True)
    return {"players": results[:top_n], "total_found": len(results)}


async def get_chip_status(team_id_override: int | None = None) -> dict:
    """
    Return which FPL chips the user has already used and which are still available.
    Uses /api/entry/{team_id}/history/ for chip history and bootstrap for current GW.
    """
    team_id = team_id_override or settings.fpl_team_id
    if not team_id:
        return {"error": "FPL_TEAM_ID is not set in config."}

    async with httpx.AsyncClient(base_url=_FPL_BASE_URL, timeout=10.0) as client:
        bootstrap = await client.get("/bootstrap-static/")
        bootstrap.raise_for_status()
        bootstrap_data = bootstrap.json()

        history_resp = await client.get(f"/entry/{team_id}/history/")
        history_resp.raise_for_status()
        history_data = history_resp.json()

    current_gw = next(
        (e["id"] for e in bootstrap_data["events"] if e["is_current"]),
        next((e["id"] for e in bootstrap_data["events"] if e["is_next"]), 1),
    )

    # Chips used so far
    used_chips = {c["name"]: c["event"] for c in history_data.get("chips", [])}

    # Wildcard: one per half-season (GW1-19 = first half, GW20-38 = second half)
    wc1_used = used_chips.get("wildcard") if used_chips.get("wildcard", 99) <= 19 else None
    wc2_used = used_chips.get("wildcard") if used_chips.get("wildcard", 0) >= 20 else None
    # If used twice, history has two separate entries — pick by event
    all_wc = [c for c in history_data.get("chips", []) if c["name"] == "wildcard"]
    wc1_used = next((c["event"] for c in all_wc if c["event"] <= 19), None)
    wc2_used = next((c["event"] for c in all_wc if c["event"] >= 20), None)

    chips = {
        "wildcard_1": {
            "available": wc1_used is None and current_gw <= 19,
            "used_in_gw": wc1_used,
            "window": "GW1–19",
        },
        "wildcard_2": {
            "available": wc2_used is None and current_gw >= 20,
            "used_in_gw": wc2_used,
            "window": "GW20–38",
        },
        "triple_captain": {
            "available": "3xc" not in used_chips,
            "used_in_gw": used_chips.get("3xc"),
        },
        "bench_boost": {
            "available": "bboost" not in used_chips,
            "used_in_gw": used_chips.get("bboost"),
        },
        "free_hit": {
            "available": "freehit" not in used_chips,
            "used_in_gw": used_chips.get("freehit"),
        },
    }

    return {"current_gameweek": current_gw, "chips": chips}


async def get_gameweek_schedule(next_n: int = 8) -> dict:
    """
    Return the upcoming N gameweeks with fixture counts per team.
    Flags double gameweeks (team plays twice) and blank gameweeks (team doesn't play).
    """
    data = await _get_bootstrap()
    events = data.get("events", [])
    team_map = {t["id"]: t["short_name"] for t in data.get("teams", [])}
    all_fixtures = data.get("fixtures", [])  # not always present in bootstrap

    # Find upcoming GWs
    current_gw = next((e["id"] for e in events if e["is_current"]), None)
    next_gw = next((e["id"] for e in events if e["is_next"]), None)
    start_gw = current_gw or next_gw or 1

    upcoming = [e for e in events if e["id"] >= start_gw][:next_n]

    # Fetch fixtures separately since bootstrap-static doesn't always include them
    async with httpx.AsyncClient(base_url=_FPL_BASE_URL, timeout=10.0) as client:
        fixtures_resp = await client.get("/fixtures/")
        fixtures_resp.raise_for_status()
        all_fixtures = fixtures_resp.json()

    # Group fixtures by GW
    fixtures_by_gw: dict[int, list] = {}
    for f in all_fixtures:
        gw = f.get("event")
        if gw is None:
            continue
        fixtures_by_gw.setdefault(gw, []).append(f)

    schedule = []
    all_team_ids = set(team_map.keys())

    for event in upcoming:
        gw_id = event["id"]
        gw_fixtures = fixtures_by_gw.get(gw_id, [])

        # Count appearances per team this GW
        team_fixture_count: dict[int, int] = {}
        gw_fixture_list = []
        for f in gw_fixtures:
            h = f.get("team_h")
            a = f.get("team_a")
            if h:
                team_fixture_count[h] = team_fixture_count.get(h, 0) + 1
            if a:
                team_fixture_count[a] = team_fixture_count.get(a, 0) + 1
            gw_fixture_list.append(f"{team_map.get(h, '?')} vs {team_map.get(a, '?')}")

        double_gw_teams = [team_map[tid] for tid, cnt in team_fixture_count.items() if cnt >= 2]
        blank_gw_teams = [
            team_map[tid] for tid in all_team_ids if team_fixture_count.get(tid, 0) == 0
        ]

        schedule.append(
            {
                "gameweek": gw_id,
                "deadline": event.get("deadline_time", "")[:16],
                "fixtures": gw_fixture_list,
                "double_gameweek_teams": sorted(double_gw_teams),
                "blank_gameweek_teams": sorted(blank_gw_teams),
                "is_double_gw": len(double_gw_teams) > 0,
                "is_blank_gw": len(blank_gw_teams) > 0,
            }
        )

    return {"gameweek_schedule": schedule}


# Tool definitions in Anthropic tool-use format.
# Claude receives these and decides which to call based on the question.
TOOL_DEFINITIONS = [
    {
        "name": "get_my_fpl_team",
        "description": (
            "Get the user's current FPL squad — player names, positions, teams, "
            "selling prices, and who is currently set as captain. "
            "Always call this first when the user asks about their team, transfers, "
            "captaincy, or anything personalised to their FPL squad."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
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
    {
        "name": "get_team_all_fixtures",
        "description": (
            "Get a team's upcoming fixtures across ALL competitions — Premier League, "
            "Champions League, FA Cup, etc. Use this to assess fixture congestion and "
            "rotation risk when a team has midweek European games."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "team_id": {
                    "type": "integer",
                    "description": "The API-Sports team ID.",
                },
                "next_n": {
                    "type": "integer",
                    "description": "Number of upcoming fixtures to return. Defaults to 7.",
                    "default": 7,
                },
            },
            "required": ["team_id"],
        },
    },
    {
        "name": "search_players_by_criteria",
        "description": (
            "Search for FPL players filtered by position and/or price using LIVE FPL data. "
            "ALWAYS use this tool when the user asks for player recommendations by position "
            "or budget (e.g. 'midfielder under £5.8m', 'best cheap defender'). "
            "Never guess player prices or positions from memory — use this tool to get "
            "accurate live prices."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "position": {
                    "type": "string",
                    "enum": ["GKP", "DEF", "MID", "FWD"],
                    "description": "Filter by position. One of: GKP, DEF, MID, FWD.",
                },
                "max_price": {
                    "type": "number",
                    "description": "Maximum price in millions, e.g. 5.8 for £5.8m.",
                },
                "min_price": {
                    "type": "number",
                    "description": "Minimum price in millions, e.g. 5.0 for £5.0m.",
                },
                "top_n": {
                    "type": "integer",
                    "description": "Number of top players to return, ranked by FPL points. Defaults to 10.",  # noqa: E501
                    "default": 10,
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_chip_status",
        "description": (
            "Get the user's FPL chip availability — which chips (Wildcard, Triple Captain, "
            "Bench Boost, Free Hit) have been used and which are still available. "
            "Always call this when the user asks about chip strategy or when to use a chip."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_gameweek_schedule",
        "description": (
            "Get the upcoming FPL gameweek schedule, flagging which gameweeks have "
            "double gameweeks (a team plays twice) or blank gameweeks (a team doesn't play). "
            "Always call this when the user asks about chip timing, especially Bench Boost, "
            "Triple Captain, Free Hit, or Wildcard timing around DGWs and BGWs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "next_n": {
                    "type": "integer",
                    "description": "Number of upcoming gameweeks to return. Defaults to 8.",
                    "default": 8,
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_player_vs_opponent",
        "description": (
            "Get a player's individual stats (goals, assists, rating) in past games "
            "against a specific opponent. Use this for h2h player performance analysis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {
                    "type": "integer",
                    "description": "The API-Sports player ID.",
                },
                "team1_id": {
                    "type": "integer",
                    "description": "The player's team ID.",
                },
                "team2_id": {
                    "type": "integer",
                    "description": "The opponent's team ID.",
                },
                "last_n": {
                    "type": "integer",
                    "description": "Number of past h2h games to look at. Defaults to 5.",
                    "default": 5,
                },
            },
            "required": ["player_id", "team1_id", "team2_id"],
        },
    },
]
