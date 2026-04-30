"""
FPL MCP tools — live data via API-Sports.

Each public function fetches data from the API-Sports football API and returns
a trimmed summary dict. Raw API responses are never passed to Claude directly —
they are too large and blow through token limits.

API-Sports docs: https://www.api-football.com/documentation-v3
Premier League ID: 39
"""

import asyncio
import time
from typing import Any

import httpx

from server.config import settings

_BASE_URL = "https://v3.football.api-sports.io"
_FPL_BASE_URL = "https://fantasy.premierleague.com/api"
_PREMIER_LEAGUE_ID = 39
_CURRENT_SEASON = "2025"  # 2025-26 season

# Persistent clients — one TCP connection pool per upstream, reused across all tool calls.
# Created lazily so tests can patch settings before the first call.
_api_sports_client: httpx.AsyncClient | None = None
_fpl_client: httpx.AsyncClient | None = None


def _get_api_sports_client() -> httpx.AsyncClient:
    global _api_sports_client
    if _api_sports_client is None or _api_sports_client.is_closed:
        _api_sports_client = httpx.AsyncClient(base_url=_BASE_URL, headers=_headers(), timeout=10.0)
    return _api_sports_client


def _get_fpl_client() -> httpx.AsyncClient:
    global _fpl_client
    if _fpl_client is None or _fpl_client.is_closed:
        _fpl_client = httpx.AsyncClient(base_url=_FPL_BASE_URL, timeout=10.0)
    return _fpl_client


_SLOW_CACHE_TTL = 6 * 3600  # 6 hours — for data that updates at most once per gameweek
_MAX_CACHE_ENTRIES = 20  # safety cap; in practice we have ~2 keys
_MISSING = object()  # sentinel — distinguishes absent entry from empty-but-valid cached result
_slow_cache: dict[str, tuple[dict[str, Any], float]] = {}
# Initialised lazily inside a coroutine so the Lock is always bound to a running event loop.
# Creating asyncio.Lock() at import time raises DeprecationWarning in Python 3.10+ and
# fails in 3.12+ when no event loop exists yet.
_slow_cache_lock: asyncio.Lock | None = None


def _get_slow_cache_lock() -> asyncio.Lock:
    global _slow_cache_lock
    if _slow_cache_lock is None:
        _slow_cache_lock = asyncio.Lock()
    return _slow_cache_lock


def _cache_get(key: str) -> Any:
    """Return the cached result for key, or _MISSING sentinel if absent or expired."""
    entry = _slow_cache.get(key, _MISSING)
    if entry is _MISSING:
        return _MISSING
    result, ts = entry
    if time.monotonic() - ts >= _SLOW_CACHE_TTL:
        return _MISSING
    return result


def _cache_set(key: str, result: dict[str, Any]) -> None:
    # Blunt eviction: clear all entries when the cap is hit. Acceptable because
    # we only ever store ~2 keys; the cap exists purely as a safety net.
    if len(_slow_cache) >= _MAX_CACHE_ENTRIES:
        _slow_cache.clear()
    _slow_cache[key] = (result, time.monotonic())


def _headers() -> dict[str, str]:
    return {"x-apisports-key": settings.api_sports_key}


async def get_fixtures(next_n: int = 10) -> dict:
    """Fetch the next N Premier League fixtures."""
    client = _get_api_sports_client()
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
    key = "standings"
    async with _get_slow_cache_lock():
        cached = _cache_get(key)
        if cached is not _MISSING:
            return cached  # type: ignore[return-value]

        client = _get_api_sports_client()
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
        result = {"standings": standings}
        _cache_set(key, result)
        return result


async def get_player_stats(player_name: str) -> dict:
    """Fetch current-season FPL stats for a player from the PostgreSQL database."""
    from server.tools.db import execute as _db_execute

    bootstrap = await _get_bootstrap()
    element = _find_player(bootstrap["elements"], player_name)
    if not element:
        return {"error": f"Player '{player_name}' not found in FPL data"}

    sql = """
        SELECT
            p.web_name,
            t.name AS team,
            p.position,
            ROUND(p.now_cost / 10.0, 1) AS price,
            p.total_points,
            p.minutes,
            p.goals_scored,
            p.assists,
            p.clean_sheets,
            p.goals_conceded,
            p.yellow_cards,
            p.red_cards,
            p.bonus,
            p.form,
            p.points_per_game,
            p.selected_by_percent,
            p.ict_index,
            ROUND(p.expected_goals::numeric, 2) AS xg,
            ROUND(p.expected_assists::numeric, 2) AS xa,
            ROUND(p.expected_goal_involvements::numeric, 2) AS xgi,
            p.status,
            p.news
        FROM players p
        JOIN seasons s ON p.season_id = s.id
        JOIN teams t ON p.team_fpl_id = t.fpl_id AND p.season_id = t.season_id
        WHERE s.is_current = TRUE
          AND p.fpl_id = $1
        LIMIT 1
    """
    result = await _db_execute(sql, (element["id"],))
    rows = result.get("rows", [])
    if not rows:
        return {"error": f"No stats found for '{player_name}' in current season"}
    return {"player_stats": rows[0]}


async def get_player_recent_form(player_name: str, last_n: int = 5) -> dict:
    """
    Fetch a player's recent FPL form — exact FPL points, minutes, goals, assists,
    clean sheets, and bonus per gameweek. Uses the FPL element-summary endpoint so
    all values are official FPL figures, not approximations.
    """
    bootstrap = await _get_bootstrap()
    team_map = {t["id"]: t["name"] for t in bootstrap["teams"]}

    element = _find_player(bootstrap["elements"], player_name)
    if not element:
        return {"error": f"Player '{player_name}' not found in FPL data"}

    client = _get_fpl_client()
    resp = await client.get(f"/element-summary/{element['id']}/")
    resp.raise_for_status()
    history = resp.json().get("history", [])

    recent = history[-last_n:] if len(history) >= last_n else history
    games = [
        {
            "round": gw.get("round"),
            "opponent": team_map.get(gw.get("opponent_team"), f"Team {gw.get('opponent_team')}"),
            "home_away": "H" if gw.get("was_home") else "A",
            "minutes": gw.get("minutes"),
            "goals": gw.get("goals_scored"),
            "assists": gw.get("assists"),
            "clean_sheet": bool(gw.get("clean_sheets")),
            "goals_conceded": gw.get("goals_conceded"),
            "yellow_cards": gw.get("yellow_cards"),
            "red_cards": gw.get("red_cards"),
            "bonus": gw.get("bonus"),
            "total_points": gw.get("total_points"),
        }
        for gw in recent
    ]
    return {
        "player": f"{element['first_name']} {element['second_name']}",
        "web_name": element["web_name"],
        "team": team_map.get(element["team"], ""),
        "recent_form": games,
    }


async def search_team(name: str) -> dict:
    """Search for a Premier League team by name to get their team ID."""
    client = _get_api_sports_client()
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
    client = _get_api_sports_client()
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
    client = _get_api_sports_client()
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
    client = _get_api_sports_client()
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
                "fixture_id": f.get("id"),
                "date": f.get("date", "")[:10],
                "competition": league.get("name"),
                "round": league.get("round"),
                "home": teams.get("home", {}).get("name"),
                "away": teams.get("away", {}).get("name"),
                "venue": f.get("venue", {}).get("name"),
            }
        )
    return {"all_fixtures": fixtures}


async def get_player_vs_opponent(player_name: str, opponent_name: str, last_n: int = 5) -> dict:
    """
    Fetch a player's FPL stats in past games against a specific opponent using
    the PostgreSQL historical database. Returns exact FPL figures: points, bonus,
    clean sheets, goals, assists, minutes per fixture.
    """
    from server.tools.db import execute as _db_execute

    bootstrap = await _get_bootstrap()

    element = _find_player(bootstrap["elements"], player_name)
    if not element:
        return {"error": f"Player '{player_name}' not found in FPL data"}

    opp_lower = opponent_name.lower()
    opp_team = None
    for t in bootstrap["teams"]:
        if opp_lower in t["name"].lower() or opp_lower in t["short_name"].lower():
            opp_team = t
            break

    if not opp_team:
        return {"error": f"Team '{opponent_name}' not found in FPL data"}

    last_n = max(1, min(int(last_n), 20))
    sql = """
        SELECT
            g.gw_number,
            CASE WHEN g.was_home THEN 'H' ELSE 'A' END AS home_away,
            g.minutes,
            g.goals_scored,
            g.assists,
            g.clean_sheets,
            g.goals_conceded,
            g.bonus,
            g.total_points,
            ROUND(g.expected_goals::numeric, 2) AS xg,
            ROUND(g.expected_assists::numeric, 2) AS xa,
            g.starts
        FROM gw_player_stats g
        WHERE g.player_fpl_id = $1
          AND g.opponent_team_fpl_id = $2
        ORDER BY g.gw_number DESC
        LIMIT $3
    """
    result = await _db_execute(sql, (element["id"], opp_team["id"], last_n))
    return {
        "player": f"{element['first_name']} {element['second_name']}",
        "opponent": opp_team["name"],
        "games": result.get("rows", []),
        "row_count": result.get("row_count", 0),
    }


async def get_odds(fixture_id: int) -> dict:
    """Fetch current odds for a fixture."""
    client = _get_api_sports_client()
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

    client = _get_fpl_client()
    bootstrap_data = await _get_bootstrap()

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

    # Build player ID → enriched map
    position_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    team_map = {t["id"]: t["name"] for t in bootstrap_data["teams"]}
    player_map = {
        p["id"]: {
            "name": f"{p['first_name']} {p['second_name']}",
            "web_name": p.get("web_name"),
            "team": team_map.get(p["team"], ""),
            "position": position_map.get(p["element_type"], ""),
            "now_cost": p.get("now_cost", 0) / 10,
            "event_points": p.get("event_points", 0),
            "total_points": p.get("total_points", 0),
            "points_per_game": p.get("points_per_game", "0"),
            "form": p.get("form", "0"),
            "minutes": p.get("minutes", 0),
            "status": p.get("status"),  # a=available d=doubtful i=injured s=suspended
            "news": p.get("news") or None,
            "chance_of_playing_this_round": p.get("chance_of_playing_this_round"),
            "chance_of_playing_next_round": p.get("chance_of_playing_next_round"),
            "selected_by_percent": p.get("selected_by_percent"),
            "transfers_in_event": p.get("transfers_in_event", 0),
            "transfers_out_event": p.get("transfers_out_event", 0),
            "expected_goals": p.get("expected_goals"),
            "expected_assists": p.get("expected_assists"),
            "expected_goal_involvements": p.get("expected_goal_involvements"),
            "ict_index": p.get("ict_index"),
        }
        for p in bootstrap_data["elements"]
    }

    # Fetch picks and entry info concurrently
    picks_resp, entry_resp = await asyncio.gather(
        client.get(f"/entry/{team_id}/event/{current_gw}/picks/"),
        client.get(f"/entry/{team_id}/"),
    )
    picks_resp.raise_for_status()
    entry_resp.raise_for_status()
    picks_data = picks_resp.json()
    entry_data = entry_resp.json()

    # User's private classic leagues (exclude global/public system leagues)
    my_leagues = [
        {
            "id": lg["id"],
            "name": lg["name"],
            "entry_rank": lg.get("entry_rank"),
            "entry_last_rank": lg.get("entry_last_rank"),
        }
        for lg in entry_data.get("leagues", {}).get("classic", [])
        if lg.get("league_type") == "c"
    ]

    entry_history = picks_data.get("entry_history", {})

    squad = []
    for pick in picks_data.get("picks", []):
        pid = pick["element"]
        info = player_map.get(pid, {})
        squad.append(
            {
                "name": info.get("name"),
                "web_name": info.get("web_name"),
                "team": info.get("team"),
                "position": info.get("position"),
                "selling_price": pick.get("selling_price", 0) / 10,
                "now_cost": info.get("now_cost"),
                "multiplier": pick.get("multiplier"),  # 2=captain, 3=TC, 0=benched
                "is_captain": pick.get("is_captain"),
                "is_vice_captain": pick.get("is_vice_captain"),
                "event_points": info.get("event_points"),
                "total_points": info.get("total_points"),
                "points_per_game": info.get("points_per_game"),
                "form": info.get("form"),
                "minutes": info.get("minutes"),
                "status": info.get("status"),
                "news": info.get("news"),
                "chance_of_playing_this_round": info.get("chance_of_playing_this_round"),
                "selected_by_percent": info.get("selected_by_percent"),
                "transfers_in_event": info.get("transfers_in_event"),
                "transfers_out_event": info.get("transfers_out_event"),
                "expected_goals": info.get("expected_goals"),
                "expected_assists": info.get("expected_assists"),
                "expected_goal_involvements": info.get("expected_goal_involvements"),
                "ict_index": info.get("ict_index"),
            }
        )

    active_chip = picks_data.get("active_chip")

    result: dict = {
        "gameweek": current_gw,
        "active_chip": active_chip,
        "itb": entry_history.get("bank", 0) / 10,
        "squad_value": entry_history.get("value", 0) / 10,
        "transfers_made_this_gw": entry_history.get("event_transfers", 0),
        "transfers_cost_this_gw": entry_history.get("event_transfers_cost", 0),
        "squad": squad,
        "my_leagues": my_leagues,
    }

    # Free Hit is active: the current squad is temporary. Fetch GW-1 picks so
    # Claude can advise on transfers against the squad that will be restored.
    if active_chip == "freehit" and current_gw > 1:
        try:
            orig_resp = await client.get(f"/entry/{team_id}/event/{current_gw - 1}/picks/")
            orig_resp.raise_for_status()
            orig_data = orig_resp.json()
            orig_squad = []
            for pick in orig_data.get("picks", []):
                pid = pick["element"]
                info = player_map.get(pid, {})
                orig_squad.append(
                    {
                        "name": info.get("name"),
                        "web_name": info.get("web_name"),
                        "team": info.get("team"),
                        "position": info.get("position"),
                        "selling_price": pick.get("selling_price", 0) / 10,
                        "now_cost": info.get("now_cost"),
                        "multiplier": pick.get("multiplier"),
                        "is_captain": pick.get("is_captain"),
                        "is_vice_captain": pick.get("is_vice_captain"),
                        "total_points": info.get("total_points"),
                        "form": info.get("form"),
                        "status": info.get("status"),
                        "news": info.get("news"),
                        "expected_goal_involvements": info.get("expected_goal_involvements"),
                        "ict_index": info.get("ict_index"),
                    }
                )
            orig_history = orig_data.get("entry_history", {})
            result["free_hit_note"] = (
                f"Free Hit is active in GW{current_gw}. The squad above is the temporary "
                f"Free Hit squad. Your original squad (restored after GW{current_gw}) is "
                f"in original_squad. Use original_squad for transfer planning."
            )
            result["original_squad"] = orig_squad
            result["original_itb"] = orig_history.get("bank", 0) / 10
        except Exception:
            result["free_hit_note"] = (
                f"Free Hit is active in GW{current_gw}. Could not fetch original squad "
                f"from GW{current_gw - 1} — ask the user to list their original players."
            )

    return result


_POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
_POSITION_IDS = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}


def _find_player(elements: list[dict], name: str) -> dict | None:
    """Find a player in the bootstrap elements list by name.

    Match priority (stops at first hit):
      1. Exact web_name match (case-insensitive) — "Son" → Son Heung-min, not Johnson
      2. Exact full-name match (case-insensitive)
      3. web_name starts-with match
      4. Substring match in web_name or full name (last resort)
    """
    q = name.strip().lower()
    for p in elements:
        if p["web_name"].lower() == q:
            return p
    full_name = lambda p: f"{p['first_name']} {p['second_name']}".lower()  # noqa: E731
    for p in elements:
        if full_name(p) == q:
            return p
    for p in elements:
        if p["web_name"].lower().startswith(q):
            return p
    for p in elements:
        if q in p["web_name"].lower() or q in full_name(p):
            return p
    return None


# ── Bootstrap cache (prices/positions from live FPL API) ──────────────────────
import time as _time  # noqa: E402

_bootstrap_cache: dict | None = None
_bootstrap_ts: float = 0
_BOOTSTRAP_TTL = 3600  # 1 hour


async def _get_bootstrap() -> dict:
    global _bootstrap_cache, _bootstrap_ts
    if _bootstrap_cache is None or _time.monotonic() - _bootstrap_ts > _BOOTSTRAP_TTL:
        r = await _get_fpl_client().get("/bootstrap-static/")
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
                "event_points": p.get("event_points", 0),
                "points_per_game": p.get("points_per_game", "0.0"),
                "form": p.get("form", "0.0"),
                "minutes": p.get("minutes", 0),
                "goals_scored": p.get("goals_scored", 0),
                "assists": p.get("assists", 0),
                "clean_sheets": p.get("clean_sheets", 0),
                "bonus": p.get("bonus", 0),
                "saves": p.get("saves", 0),
                "expected_goals": p.get("expected_goals"),
                "expected_assists": p.get("expected_assists"),
                "expected_goal_involvements": p.get("expected_goal_involvements"),
                "ict_index": p.get("ict_index"),
                "selected_by_percent": p.get("selected_by_percent", "0.0"),
                "transfers_in_event": p.get("transfers_in_event", 0),
                "transfers_out_event": p.get("transfers_out_event", 0),
                "status": p.get("status"),
                "news": p.get("news") or None,
                "chance_of_playing_this_round": p.get("chance_of_playing_this_round"),
            }
        )

    # Sort by form descending — transfer recommendations need in-form players first,
    # not season-long accumulators who may have gone cold.
    results.sort(key=lambda x: float(x["form"] or 0), reverse=True)
    return {"players": results[:top_n], "total_found": len(results)}


async def get_chip_status(team_id_override: int | None = None) -> dict:
    """
    Return which FPL chips the user has already used and which are still available.
    Uses /api/entry/{team_id}/history/ for chip history and bootstrap for current GW.
    """
    team_id = team_id_override or settings.fpl_team_id
    if not team_id:
        return {"error": "FPL_TEAM_ID is not set in config."}

    client = _get_fpl_client()
    bootstrap_data = await _get_bootstrap()

    history_resp = await client.get(f"/entry/{team_id}/history/")
    history_resp.raise_for_status()
    history_data = history_resp.json()

    current_gw = next(
        (e["id"] for e in bootstrap_data["events"] if e["is_current"]),
        next((e["id"] for e in bootstrap_data["events"] if e["is_next"]), 1),
    )

    all_chips = history_data.get("chips", [])

    # Wildcard: one per half-season (GW1-19 = first half, GW20-38 = second half)
    all_wc = [c for c in all_chips if c["name"] == "wildcard"]
    wc1_used = next((c["event"] for c in all_wc if c["event"] <= 19), None)
    wc2_used = next((c["event"] for c in all_wc if c["event"] >= 20), None)

    # TC, Bench Boost, Free Hit reset after GW19 in the 2024/25 season.
    # A chip is only considered spent if it was used in GW20+ (post-reset).
    # Uses before the reset are preserved for display but don't block availability.
    _RESET_GW = 19

    def _chip_status(api_name: str) -> dict:
        uses = [c["event"] for c in all_chips if c["name"] == api_name]
        pre_reset = [gw for gw in uses if gw <= _RESET_GW]
        post_reset = [gw for gw in uses if gw > _RESET_GW]
        if current_gw > _RESET_GW:
            # Only post-reset use counts as spending the chip
            available = len(post_reset) == 0
            used_in_gw = post_reset[0] if post_reset else None
        else:
            available = len(uses) == 0
            used_in_gw = uses[0] if uses else None
        result: dict = {"available": available, "used_in_gw": used_in_gw}
        if pre_reset and current_gw > _RESET_GW:
            result["used_pre_reset_in_gw"] = pre_reset[0]
        return result

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
        "triple_captain": _chip_status("3xc"),
        "bench_boost": _chip_status("bboost"),
        "free_hit": _chip_status("freehit"),
    }

    return {"current_gameweek": current_gw, "chips": chips}


async def get_gameweek_schedule(next_n: int = 8) -> dict:
    """
    Return the upcoming N gameweeks with fixture counts per team.
    Flags double gameweeks (team plays twice) and blank gameweeks (team doesn't play).
    """
    key = f"gameweek_schedule_{next_n}"
    async with _get_slow_cache_lock():
        cached = _cache_get(key)
        if cached is not _MISSING:
            return cached  # type: ignore[return-value]

        data = await _get_bootstrap()
        events = data.get("events", [])
        team_map = {t["id"]: t["short_name"] for t in data.get("teams", [])}

        current_gw = next((e["id"] for e in events if e["is_current"]), None)
        next_gw = next((e["id"] for e in events if e["is_next"]), None)
        start_gw = current_gw or next_gw or 1
        upcoming = [e for e in events if e["id"] >= start_gw][:next_n]

        fixtures_resp = await _get_fpl_client().get("/fixtures/")
        fixtures_resp.raise_for_status()
        all_fixtures = fixtures_resp.json()

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

            team_fixture_count: dict[int, int] = {}
            gw_fixture_list = []
            for f in gw_fixtures:
                h = f.get("team_h")
                a = f.get("team_a")
                if h:
                    team_fixture_count[h] = team_fixture_count.get(h, 0) + 1
                if a:
                    team_fixture_count[a] = team_fixture_count.get(a, 0) + 1
                gw_fixture_list.append(
                    {
                        "home": team_map.get(h, "?"),
                        "away": team_map.get(a, "?"),
                        "home_difficulty": f.get("team_h_difficulty"),
                        "away_difficulty": f.get("team_a_difficulty"),
                    }
                )

            double_gw_teams = [team_map[tid] for tid, cnt in team_fixture_count.items() if cnt >= 2]
            # Only flag blanks when the GW has fixtures assigned — if no fixtures exist yet
            # the GW is simply unscheduled, not a genuine blank gameweek.
            blank_gw_teams = (
                [team_map[tid] for tid in all_team_ids if team_fixture_count.get(tid, 0) == 0]
                if gw_fixtures
                else []
            )

            entry: dict = {
                "gameweek": gw_id,
                "deadline": event.get("deadline_time", "")[:16],
                "fixtures": gw_fixture_list,
                "double_gameweek_teams": sorted(double_gw_teams),
                "blank_gameweek_teams": sorted(blank_gw_teams),
                "is_double_gw": len(double_gw_teams) > 0,
                "is_blank_gw": len(blank_gw_teams) > 0,
            }
            # Rearranged fixtures are held at event=null until officially confirmed,
            # so blank_gw_teams can contain false positives. Attach a warning inline
            # so Claude sees it adjacent to the data and knows to verify.
            if blank_gw_teams:
                entry["blank_gw_warning"] = (
                    "UNVERIFIED — the FPL API holds rearranged fixtures at event=null, "
                    "so these teams may have a fixture not counted here. "
                    "You MUST call get_team_all_fixtures for every team listed in "
                    "blank_gameweek_teams before reporting them as blank."
                )
            schedule.append(entry)

        result = {"gameweek_schedule": schedule}
        _cache_set(key, result)
        return result


# Tool definitions in Anthropic tool-use format.
async def get_mini_league_standings(league_id: int, top_n: int = 20) -> dict:
    """Fetch standings for a classic FPL mini-league by ID."""
    client = _get_fpl_client()
    resp = await client.get(f"/leagues-classic/{league_id}/standings/")
    resp.raise_for_status()
    data = resp.json()

    league_info = data.get("league", {})
    results = []
    for entry in data.get("standings", {}).get("results", [])[:top_n]:
        results.append(
            {
                "rank": entry.get("rank"),
                "last_rank": entry.get("last_rank"),
                "manager": entry.get("player_name"),
                "team_name": entry.get("entry_name"),
                "total_points": entry.get("total"),
                "gw_points": entry.get("event_total"),
            }
        )

    return {
        "league_name": league_info.get("name"),
        "league_id": league_info.get("id"),
        "standings": results,
        "has_more": data.get("standings", {}).get("has_next", False),
    }


async def get_captain_options(player_names: list[str]) -> dict:
    """
    Batch-fetch captaincy analysis for up to 8 players concurrently.
    Returns last-5-GW points, form, ownership, next fixture + difficulty for each.
    Use this instead of calling get_player_recent_form repeatedly per candidate.
    """
    bootstrap = await _get_bootstrap()
    team_short = {t["id"]: t["short_name"] for t in bootstrap["teams"]}

    events = bootstrap.get("events", [])
    next_gw = next((e["id"] for e in events if e["is_next"]), None)
    current_gw = next((e["id"] for e in events if e["is_current"]), None)
    target_gw = next_gw or ((current_gw + 1) if current_gw else 1)

    client = _get_fpl_client()

    # Fetch next-GW fixtures once to build team → fixture lookup
    fix_resp = await client.get("/fixtures/", params={"event": target_gw})
    fix_resp.raise_for_status()
    team_fixture: dict[int, dict] = {}
    for f in fix_resp.json():
        h, a = f.get("team_h"), f.get("team_a")
        if h:
            team_fixture[h] = {
                "opponent": team_short.get(a, ""),
                "difficulty": f.get("team_h_difficulty"),
                "home_away": "H",
            }
        if a:
            team_fixture[a] = {
                "opponent": team_short.get(h, ""),
                "difficulty": f.get("team_a_difficulty"),
                "home_away": "A",
            }

    candidates = [
        el for name in player_names[:8] if (el := _find_player(bootstrap["elements"], name))
    ]
    not_found = [n for n in player_names[:8] if not _find_player(bootstrap["elements"], n)]

    async def _fetch(el: dict) -> tuple[dict, list[int]]:
        resp = await client.get(f"/element-summary/{el['id']}/")
        resp.raise_for_status()
        history = resp.json().get("history", [])
        pts = [gw["total_points"] for gw in history[-5:]]
        return el, pts

    summaries = await asyncio.gather(*(_fetch(el) for el in candidates), return_exceptions=True)

    results = []
    for item in summaries:
        if isinstance(item, Exception):
            continue
        el, pts = item
        fix = team_fixture.get(el["team"], {})
        results.append(
            {
                "name": el["web_name"],
                "team": team_short.get(el["team"], ""),
                "form": el.get("form"),
                "ownership": el.get("selected_by_percent"),
                "price": el.get("now_cost", 0) / 10,
                "status": el.get("status"),
                "chance_of_playing_this_round": el.get("chance_of_playing_this_round"),
                "last_5_gw_points": pts,
                "last_5_total": sum(pts),
                "next_fixture_opponent": fix.get("opponent"),
                "next_fixture_difficulty": fix.get("difficulty"),
                "next_fixture_home_away": fix.get("home_away"),
            }
        )

    results.sort(key=lambda x: x["last_5_total"], reverse=True)
    return {
        "gameweek": target_gw,
        "captain_options": results,
        "not_found": not_found,
    }


async def get_player_xpts(
    player_names: list[str] | None = None,
    position: str | None = None,
    top_n: int = 10,
) -> dict:
    """Return expected FPL points for the next GW from the player_xpts materialized view."""
    from server.tools import db as db_tool

    where_parts: list[str] = []
    params: list = []

    if player_names:
        ilike_clauses = []
        for name in player_names:
            params.append(f"%{name}%")
            ilike_clauses.append(f"web_name ILIKE ${len(params)}")
        where_parts.append(f"({' OR '.join(ilike_clauses)})")

    if position:
        params.append(position.upper())
        where_parts.append(f"position = ${len(params)}")

    params.append(top_n)
    limit_ph = f"${len(params)}"
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    sql = f"""
        SELECT
            web_name, position, team_name,
            ROUND(now_cost / 10.0, 1)    AS price,
            xpts,
            xpts_goals, xpts_assists, xpts_cs, xpts_saves, xpts_bonus, xpts_minutes,
            status, chance_of_playing_next_round,
            opponents, fdrs, home_flags,
            gw_number, sample_gws,
            ROUND(avg_xg::NUMERIC, 3)    AS avg_xg_per_start,
            ROUND(avg_xa::NUMERIC, 3)    AS avg_xa_per_start,
            ROUND(avg_minutes::NUMERIC)  AS avg_minutes_per_start
        FROM player_xpts
        {where_sql}
        ORDER BY xpts DESC
        LIMIT {limit_ph}
    """

    result = await db_tool.execute(sql, tuple(params))
    if result.get("error"):
        return result

    players = []
    for row in result.get("rows", []):
        opponents = row.get("opponents") or []
        fdrs = row.get("fdrs") or []
        home_flags = row.get("home_flags") or []
        fixtures = [
            {"opponent": opp, "fdr": fdr, "is_home": home}
            for opp, fdr, home in zip(opponents, fdrs, home_flags)
        ]
        players.append(
            {
                "name": row["web_name"],
                "position": row["position"],
                "team": row["team_name"],
                "price": row["price"],
                "xpts": row["xpts"],
                "breakdown": {
                    "goals": row["xpts_goals"],
                    "assists": row["xpts_assists"],
                    "clean_sheet": row["xpts_cs"],
                    "saves": row["xpts_saves"],
                    "bonus": row["xpts_bonus"],
                    "minutes": row["xpts_minutes"],
                },
                "fixtures": fixtures,
                "status": row["status"],
                "chance_of_playing": row["chance_of_playing_next_round"],
                "sample_gws": row["sample_gws"],
                "avg_xg_per_start": row["avg_xg_per_start"],
                "avg_xa_per_start": row["avg_xa_per_start"],
                "avg_minutes_per_start": row["avg_minutes_per_start"],
            }
        )

    return {
        "gameweek": result["rows"][0]["gw_number"] if result["rows"] else None,
        "players": players,
        "note": (
            "xpts = expected FPL points based on last-5-GW xG/xA rates + FDR-derived CS "
            "probability + avg bonus. DGW players reflect both fixtures."
        ),
    }


# Claude receives these and decides which to call based on the question.
TOOL_DEFINITIONS = [
    {
        "name": "get_my_fpl_team",
        "description": (
            "Get the user's current FPL squad with full player data: names, positions, "
            "teams, selling price, now_cost, event_points, form, total_points, "
            "points_per_game, minutes, xG, xA, xGI, ICT index, ownership %, "
            "injury status/news, chance_of_playing, GW transfer trends, "
            "plus squad-level data: ITB (in the bank), squad value, "
            "transfers made and cost this GW. "
            "Also returns my_leagues — the user's private classic mini-leagues with IDs "
            "needed to call get_mini_league_standings. "
            "Always call this first for any squad, transfer, captaincy, chip, or league question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
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
            "Get current-season FPL stats for a player: total points, goals, assists, "
            "clean sheets, minutes, bonus, form, xG, xA, xGI, ICT index, price, "
            "ownership, and injury status. Use for captain or transfer decisions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {
                    "type": "string",
                    "description": "Player name (web name or full name), e.g. 'Salah' or 'Haaland'.",  # noqa: E501
                }
            },
            "required": ["player_name"],
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
            "Get a player's recent FPL form — exact FPL points, minutes, goals, assists, "
            "clean sheets, and bonus per gameweek. All values are official FPL figures. "
            "Use this to assess form for captaincy or transfer decisions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {
                    "type": "string",
                    "description": "The player's name (web name or full name).",
                },
                "last_n": {
                    "type": "integer",
                    "description": "Number of recent gameweeks to return. Defaults to 5.",
                    "default": 5,
                },
            },
            "required": ["player_name"],
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
            "Champions League, FA Cup, etc. Use this to assess fixture congestion, "
            "rotation risk, and to verify double or blank gameweeks. "
            "Use this to cross-check DGW/BGW data from get_gameweek_schedule, as the "
            "FPL API can miss rearranged fixtures — this tool (via API-Sports) is more "
            "reliable for confirming a team's exact fixture count in a given week."
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
            "Triple Captain, Free Hit, or Wildcard timing around DGWs and BGWs. "
            "IMPORTANT LIMITATION: the FPL API sometimes assigns rearranged fixtures "
            "event=null until officially confirmed, which means this tool can under-report "
            "DGWs. Always cross-check by also calling get_team_all_fixtures for any team "
            "you suspect has a double or blank gameweek, to verify their fixture count."
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
            "Get a player's exact FPL stats (points, bonus, CS, goals, assists, xG, minutes) "
            "in past games against a specific opponent, pulled from the historical database. "
            "Use this for h2h player performance analysis and captaincy decisions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {
                    "type": "string",
                    "description": "The player's name (web name or full name).",
                },
                "opponent_name": {
                    "type": "string",
                    "description": "The opponent team's name or short name.",
                },
                "last_n": {
                    "type": "integer",
                    "description": "Number of past games to return. Defaults to 5.",
                    "default": 5,
                },
            },
            "required": ["player_name", "opponent_name"],
        },
    },
    {
        "name": "get_captain_options",
        "description": (
            "Batch-fetch captaincy data for up to 8 players in a single call. "
            "Returns last-5-GW points breakdown, form score, ownership %, price, "
            "next fixture opponent + difficulty (1=easy 5=hard), and injury status for each. "
            "Use this instead of calling get_player_recent_form repeatedly — "
            "it fetches all candidates concurrently and returns them ranked by recent total points. "  # noqa: E501
            "Always call this for captaincy questions with the realistic candidates from the squad."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of player web names to compare (max 8). "
                        "Use the web_name field from get_my_fpl_team."
                    ),
                }
            },
            "required": ["player_names"],
        },
    },
    {
        "name": "get_mini_league_standings",
        "description": (
            "Get standings for a user's FPL classic mini-league. "
            "Use the league IDs from my_leagues in get_my_fpl_team to find the right ID. "
            "Returns rank, last week's rank, manager name, team name, total points, and GW points "
            "for each entry in the league."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "league_id": {
                    "type": "integer",
                    "description": "The FPL league ID from my_leagues in get_my_fpl_team.",
                },
                "top_n": {
                    "type": "integer",
                    "description": "Number of entries to return. Defaults to 20.",
                    "default": 20,
                },
            },
            "required": ["league_id"],
        },
    },
    {
        "name": "get_player_xpts",
        "description": (
            "Return expected FPL points (xPts) for the next gameweek, computed from each "
            "player's last-5-GW xG/xA rates, FDR-based clean sheet probability, and avg bonus. "
            "DGW players automatically score double (both fixtures summed). "
            "Use this for: transfer target ranking, captain comparison by projected output, "
            "lineup decisions (who to start/bench), and differential spotting. "
            "Pass player_names to compare specific players, or omit it to get the top N "
            "by position or overall. Do NOT use query_database for xPts — use this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of player web names to fetch xPts for (e.g. ['Salah', 'Palmer']). "
                        "Omit to return top_n players overall or filtered by position."
                    ),
                },
                "position": {
                    "type": "string",
                    "enum": ["GKP", "DEF", "MID", "FWD"],
                    "description": "Filter by position. Omit for all positions.",
                },
                "top_n": {
                    "type": "integer",
                    "description": "Max players to return. Defaults to 10.",
                    "default": 10,
                },
            },
            "required": [],
        },
    },
]


def get_tool_definitions() -> list[dict]:
    from server.tools.db import TOOL_DEFINITION as DB_TOOL

    return TOOL_DEFINITIONS + [DB_TOOL]
