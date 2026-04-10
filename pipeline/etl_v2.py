"""
Gaffer V2 ETL pipeline.

Populates the PostgreSQL database from two sources:
  - API-Sports: historical seasons (2020/21 → 2024/25) and current season enrichment
  - FPL API: current season GW-by-GW player stats, squad snapshots, fixtures

Run modes:
  python -m pipeline.etl_v2 --mode=backfill   # one-time historical import (API-Sports)
  python -m pipeline.etl_v2 --mode=full        # full current season refresh (FPL API)
  python -m pipeline.etl_v2 --mode=gw          # post-gameweek update (FPL API gw_player_stats)
  python -m pipeline.etl_v2 --mode=snapshot    # hourly players/fixtures snapshot (FPL API)

Table population order (respects FK dependencies):
  1. seasons
  2. teams
  3. gameweeks
  4. players
  5. fixtures
  6. gw_player_stats
"""

import argparse
import asyncio
import logging
from datetime import datetime

import asyncpg
import httpx

from server.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_FPL_BASE = "https://fantasy.premierleague.com/api"
_SPORTS_BASE = "https://v3.football.api-sports.io"
_PL_LEAGUE_ID = 39
_POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# Seasons to backfill from API-Sports (start year → label)
_BACKFILL_SEASONS = {
    2020: "2020/21",
    2021: "2021/22",
    2022: "2022/23",
    2023: "2023/24",
    2024: "2024/25",
}

# API-Sports position string → our schema position
_SPORTS_POSITION_MAP = {
    "Goalkeeper": "GKP",
    "Defender": "DEF",
    "Midfielder": "MID",
    "Attacker": "FWD",
}


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------


async def get_conn() -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def _fpl_get(client: httpx.AsyncClient, path: str) -> dict:
    r = await client.get(f"{_FPL_BASE}{path}")
    r.raise_for_status()
    return r.json()


async def _sports_get(client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict:
    r = await client.get(
        f"{_SPORTS_BASE}{path}",
        params=params or {},
        headers={"x-apisports-key": settings.api_sports_key},
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _current_season_label(bootstrap: dict) -> str:
    """Derive season label from FPL bootstrap events, e.g. '2025/26'."""
    try:
        year = int(bootstrap["events"][0]["deadline_time"][:4])
        return f"{year}/{str(year + 1)[2:]}"
    except (KeyError, IndexError, ValueError):
        return "unknown"


def _current_season_start_year(bootstrap: dict) -> int:
    try:
        return int(bootstrap["events"][0]["deadline_time"][:4])
    except (KeyError, IndexError, ValueError):
        return datetime.now(datetime.UTC).year  # noqa: DTZ005


# ---------------------------------------------------------------------------
# FPL API — current season
# ---------------------------------------------------------------------------


async def upsert_current_season(conn: asyncpg.Connection, bootstrap: dict) -> int:
    """Insert/update the current season row. Returns season.id."""
    label = _current_season_label(bootstrap)
    start_year = _current_season_start_year(bootstrap)

    # Clear any stale is_current flag
    await conn.execute("UPDATE seasons SET is_current = FALSE WHERE is_current = TRUE")

    row = await conn.fetchrow(
        """
        INSERT INTO seasons (label, start_year, is_current)
        VALUES ($1, $2, TRUE)
        ON CONFLICT (label) DO UPDATE
            SET is_current = TRUE, start_year = EXCLUDED.start_year
        RETURNING id
        """,
        label,
        start_year,
    )
    log.info("season upserted: %s (id=%d)", label, row["id"])
    return row["id"]


async def upsert_teams(conn: asyncpg.Connection, season_id: int, bootstrap: dict) -> dict[int, str]:
    """Upsert all PL teams. Returns {fpl_id: name} map."""
    teams_map: dict[int, str] = {}
    for t in bootstrap["teams"]:
        await conn.execute(
            """
            INSERT INTO teams (
                season_id, fpl_id, name, short_name, strength,
                strength_attack_home, strength_attack_away,
                strength_defence_home, strength_defence_away
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (season_id, fpl_id) DO UPDATE SET
                name = EXCLUDED.name,
                short_name = EXCLUDED.short_name,
                strength = EXCLUDED.strength,
                strength_attack_home = EXCLUDED.strength_attack_home,
                strength_attack_away = EXCLUDED.strength_attack_away,
                strength_defence_home = EXCLUDED.strength_defence_home,
                strength_defence_away = EXCLUDED.strength_defence_away
            """,
            season_id,
            t["id"],
            t["name"],
            t["short_name"],
            t.get("strength"),
            t.get("strength_attack_home"),
            t.get("strength_attack_away"),
            t.get("strength_defence_home"),
            t.get("strength_defence_away"),
        )
        teams_map[t["id"]] = t["name"]
    log.info("upserted %d teams", len(teams_map))
    return teams_map


async def upsert_gameweeks(conn: asyncpg.Connection, season_id: int, bootstrap: dict) -> None:
    """Upsert all gameweeks from FPL bootstrap events."""
    for e in bootstrap["events"]:
        await conn.execute(
            """
            INSERT INTO gameweeks (
                season_id, gw_number, name, deadline_time,
                average_entry_score, highest_score,
                most_selected_fpl_id, most_transferred_in_fpl_id,
                top_element_fpl_id, top_element_points,
                is_current, is_next, is_finished
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (season_id, gw_number) DO UPDATE SET
                name = EXCLUDED.name,
                deadline_time = EXCLUDED.deadline_time,
                average_entry_score = EXCLUDED.average_entry_score,
                highest_score = EXCLUDED.highest_score,
                most_selected_fpl_id = EXCLUDED.most_selected_fpl_id,
                most_transferred_in_fpl_id = EXCLUDED.most_transferred_in_fpl_id,
                top_element_fpl_id = EXCLUDED.top_element_fpl_id,
                top_element_points = EXCLUDED.top_element_points,
                is_current = EXCLUDED.is_current,
                is_next = EXCLUDED.is_next,
                is_finished = EXCLUDED.is_finished
            """,
            season_id,
            e["id"],
            e["name"],
            e.get("deadline_time"),
            e.get("average_entry_score"),
            e.get("highest_score"),
            e.get("most_selected"),
            e.get("most_transferred_in"),
            e.get("top_element"),
            (e.get("top_element_info") or {}).get("points"),
            e.get("is_current", False),
            e.get("is_next", False),
            e.get("finished", False),
        )
    log.info("upserted %d gameweeks", len(bootstrap["events"]))


async def upsert_players(conn: asyncpg.Connection, season_id: int, bootstrap: dict) -> list[int]:
    """Upsert all FPL players. Returns list of fpl_ids."""
    fpl_ids = []
    for p in bootstrap["elements"]:
        position = _POSITION_MAP.get(p["element_type"], "MID")
        await conn.execute(
            """
            INSERT INTO players (
                season_id, fpl_id, team_fpl_id, first_name, second_name, web_name,
                position, now_cost, start_cost, total_points, minutes,
                goals_scored, assists, clean_sheets, goals_conceded,
                yellow_cards, red_cards, bonus, form, points_per_game,
                selected_by_percent, transfers_in_event, transfers_out_event,
                status, chance_of_playing_next_round, news,
                creativity, influence, threat, ict_index,
                expected_goals, expected_assists, expected_goal_involvements,
                photo, updated_at
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                $16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,
                $29,$30,$31,$32,$33,$34,NOW()
            )
            ON CONFLICT (season_id, fpl_id) DO UPDATE SET
                team_fpl_id = EXCLUDED.team_fpl_id,
                now_cost = EXCLUDED.now_cost,
                total_points = EXCLUDED.total_points,
                minutes = EXCLUDED.minutes,
                goals_scored = EXCLUDED.goals_scored,
                assists = EXCLUDED.assists,
                clean_sheets = EXCLUDED.clean_sheets,
                goals_conceded = EXCLUDED.goals_conceded,
                yellow_cards = EXCLUDED.yellow_cards,
                red_cards = EXCLUDED.red_cards,
                bonus = EXCLUDED.bonus,
                form = EXCLUDED.form,
                points_per_game = EXCLUDED.points_per_game,
                selected_by_percent = EXCLUDED.selected_by_percent,
                transfers_in_event = EXCLUDED.transfers_in_event,
                transfers_out_event = EXCLUDED.transfers_out_event,
                status = EXCLUDED.status,
                chance_of_playing_next_round = EXCLUDED.chance_of_playing_next_round,
                news = EXCLUDED.news,
                creativity = EXCLUDED.creativity,
                influence = EXCLUDED.influence,
                threat = EXCLUDED.threat,
                ict_index = EXCLUDED.ict_index,
                expected_goals = EXCLUDED.expected_goals,
                expected_assists = EXCLUDED.expected_assists,
                expected_goal_involvements = EXCLUDED.expected_goal_involvements,
                updated_at = NOW()
            """,
            season_id,
            p["id"],
            p["team"],
            p["first_name"],
            p["second_name"],
            p["web_name"],
            position,
            p.get("now_cost"),
            p.get("cost_change_start"),
            p.get("total_points"),
            p.get("minutes"),
            p.get("goals_scored"),
            p.get("assists"),
            p.get("clean_sheets"),
            p.get("goals_conceded"),
            p.get("yellow_cards"),
            p.get("red_cards"),
            p.get("bonus"),
            float(p["form"]) if p.get("form") else None,
            float(p["points_per_game"]) if p.get("points_per_game") else None,
            float(p["selected_by_percent"]) if p.get("selected_by_percent") else None,
            p.get("transfers_in_event"),
            p.get("transfers_out_event"),
            p.get("status"),
            p.get("chance_of_playing_next_round"),
            p.get("news"),
            float(p["creativity"]) if p.get("creativity") else None,
            float(p["influence"]) if p.get("influence") else None,
            float(p["threat"]) if p.get("threat") else None,
            float(p["ict_index"]) if p.get("ict_index") else None,
            float(p["expected_goals"]) if p.get("expected_goals") else None,
            float(p["expected_assists"]) if p.get("expected_assists") else None,
            float(p["expected_goal_involvements"]) if p.get("expected_goal_involvements") else None,
            p.get("photo"),
        )
        fpl_ids.append(p["id"])
    log.info("upserted %d players", len(fpl_ids))
    return fpl_ids


async def upsert_fixtures_fpl(conn: asyncpg.Connection, season_id: int, all_fixtures: list) -> None:
    """Upsert all fixtures from FPL /fixtures/ endpoint."""
    for f in all_fixtures:
        await conn.execute(
            """
            INSERT INTO fixtures (
                season_id, fpl_id, gw_number, kickoff_time,
                home_team_fpl_id, away_team_fpl_id,
                home_score, away_score, finished, started,
                home_team_difficulty, away_team_difficulty,
                minutes, provisional_start_time
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            ON CONFLICT (season_id, fpl_id) DO UPDATE SET
                gw_number = EXCLUDED.gw_number,
                kickoff_time = EXCLUDED.kickoff_time,
                home_score = EXCLUDED.home_score,
                away_score = EXCLUDED.away_score,
                finished = EXCLUDED.finished,
                started = EXCLUDED.started,
                home_team_difficulty = EXCLUDED.home_team_difficulty,
                away_team_difficulty = EXCLUDED.away_team_difficulty,
                minutes = EXCLUDED.minutes,
                provisional_start_time = EXCLUDED.provisional_start_time
            """,
            season_id,
            f["id"],
            f.get("event"),  # NULL for postponed
            f.get("kickoff_time"),
            f["team_h"],
            f["team_a"],
            f.get("team_h_score"),
            f.get("team_a_score"),
            f.get("finished", False),
            f.get("started", False),
            # Note: FPL API team_h_difficulty is the difficulty FOR the away team
            # and team_a_difficulty is the difficulty FOR the home team — swap them
            f.get("team_a_difficulty"),  # home_team_difficulty
            f.get("team_h_difficulty"),  # away_team_difficulty
            f.get("minutes", 0),
            f.get("provisional_start_time", False),
        )
    log.info("upserted %d fixtures", len(all_fixtures))


async def upsert_gw_stats_fpl(
    conn: asyncpg.Connection,
    season_id: int,
    player_fpl_id: int,
    history: list,
) -> int:
    """Upsert GW-by-GW stats for one player from FPL element-summary history."""
    count = 0
    for g in history:
        await conn.execute(
            """
            INSERT INTO gw_player_stats (
                season_id, player_fpl_id, gw_number, fixture_fpl_id,
                opponent_team_fpl_id, was_home,
                team_h_score, team_a_score,
                minutes, goals_scored, assists, clean_sheets,
                goals_conceded, own_goals, penalties_saved, penalties_missed,
                yellow_cards, red_cards, saves, bonus, bps, total_points,
                value, selected, transfers_in, transfers_out, transfers_balance,
                influence, creativity, threat, ict_index,
                expected_goals, expected_assists,
                expected_goal_involvements, expected_goals_conceded, starts
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                $17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,
                $31,$32,$33,$34,$35,$36
            )
            ON CONFLICT (season_id, player_fpl_id, fixture_fpl_id) DO UPDATE SET
                total_points = EXCLUDED.total_points,
                minutes = EXCLUDED.minutes,
                goals_scored = EXCLUDED.goals_scored,
                assists = EXCLUDED.assists,
                clean_sheets = EXCLUDED.clean_sheets,
                goals_conceded = EXCLUDED.goals_conceded,
                bonus = EXCLUDED.bonus,
                bps = EXCLUDED.bps,
                saves = EXCLUDED.saves,
                yellow_cards = EXCLUDED.yellow_cards,
                red_cards = EXCLUDED.red_cards,
                influence = EXCLUDED.influence,
                creativity = EXCLUDED.creativity,
                threat = EXCLUDED.threat,
                ict_index = EXCLUDED.ict_index,
                expected_goals = EXCLUDED.expected_goals,
                expected_assists = EXCLUDED.expected_assists,
                expected_goal_involvements = EXCLUDED.expected_goal_involvements,
                expected_goals_conceded = EXCLUDED.expected_goals_conceded,
                starts = EXCLUDED.starts,
                value = EXCLUDED.value,
                selected = EXCLUDED.selected,
                transfers_in = EXCLUDED.transfers_in,
                transfers_out = EXCLUDED.transfers_out,
                transfers_balance = EXCLUDED.transfers_balance
            """,
            season_id,
            player_fpl_id,
            g["round"],
            g["fixture"],
            g["opponent_team"],
            g["was_home"],
            g.get("team_h_score"),
            g.get("team_a_score"),
            g.get("minutes", 0),
            g.get("goals_scored", 0),
            g.get("assists", 0),
            g.get("clean_sheets", 0),
            g.get("goals_conceded", 0),
            g.get("own_goals", 0),
            g.get("penalties_saved", 0),
            g.get("penalties_missed", 0),
            g.get("yellow_cards", 0),
            g.get("red_cards", 0),
            g.get("saves", 0),
            g.get("bonus", 0),
            g.get("bps", 0),
            g.get("total_points", 0),
            g.get("value"),
            g.get("selected"),
            g.get("transfers_in"),
            g.get("transfers_out"),
            g.get("transfers_balance"),
            float(g["influence"]) if g.get("influence") else None,
            float(g["creativity"]) if g.get("creativity") else None,
            float(g["threat"]) if g.get("threat") else None,
            float(g["ict_index"]) if g.get("ict_index") else None,
            float(g["expected_goals"]) if g.get("expected_goals") else None,
            float(g["expected_assists"]) if g.get("expected_assists") else None,
            float(g["expected_goal_involvements"]) if g.get("expected_goal_involvements") else None,
            float(g["expected_goals_conceded"]) if g.get("expected_goals_conceded") else None,
            g.get("starts"),
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# API-Sports — historical backfill
# ---------------------------------------------------------------------------


async def backfill_season(
    conn: asyncpg.Connection,
    client: httpx.AsyncClient,
    start_year: int,
    label: str,
) -> None:
    """Backfill one past season from API-Sports."""
    log.info("backfilling season %s...", label)

    # 1 — Ensure season row exists
    await conn.execute("UPDATE seasons SET is_current = FALSE WHERE label = $1", label)
    season_row = await conn.fetchrow(
        """
        INSERT INTO seasons (label, start_year, is_current)
        VALUES ($1, $2, FALSE)
        ON CONFLICT (label) DO UPDATE SET start_year = EXCLUDED.start_year
        RETURNING id
        """,
        label,
        start_year,
    )
    season_id = season_row["id"]
    log.info("season_id=%d for %s", season_id, label)

    # 2 — Teams
    data = await _sports_get(
        client,
        "/teams",
        {"league": _PL_LEAGUE_ID, "season": start_year},
    )
    teams_map: dict[int, str] = {}
    for item in data.get("response", []):
        t = item["team"]
        await conn.execute(
            """
            INSERT INTO teams (season_id, fpl_id, name, short_name)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (season_id, fpl_id) DO UPDATE SET
                name = EXCLUDED.name, short_name = EXCLUDED.short_name
            """,
            season_id,
            t["id"],
            t["name"],
            t.get("code") or t["name"][:3].upper(),
        )
        teams_map[t["id"]] = t["name"]
    log.info("upserted %d teams for %s", len(teams_map), label)

    # 3 — Fixtures
    data = await _sports_get(
        client,
        "/fixtures",
        {"league": _PL_LEAGUE_ID, "season": start_year},
    )
    fixture_ids: list[int] = []
    for item in data.get("response", []):
        f = item["fixture"]
        teams = item["teams"]
        goals = item["goals"]
        league = item["league"]
        await conn.execute(
            """
            INSERT INTO fixtures (
                season_id, fpl_id, gw_number, kickoff_time,
                home_team_fpl_id, away_team_fpl_id,
                home_score, away_score, finished
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (season_id, fpl_id) DO UPDATE SET
                home_score = EXCLUDED.home_score,
                away_score = EXCLUDED.away_score,
                finished = EXCLUDED.finished
            """,
            season_id,
            f["id"],
            league.get("round", "").split(" ")[-1]
            if "Gameweek" in (league.get("round") or "")
            else None,
            f.get("date"),
            teams["home"]["id"],
            teams["away"]["id"],
            goals.get("home"),
            goals.get("away"),
            f["status"]["short"] == "FT",
        )
        if f["status"]["short"] == "FT":
            fixture_ids.append(f["id"])
    log.info("upserted %d fixtures for %s (%d finished)", len(fixture_ids), label, len(fixture_ids))

    # 4 — Players (paginated)
    players_map: dict[int, dict] = {}
    page = 1
    while True:
        data = await _sports_get(
            client,
            "/players",
            {"league": _PL_LEAGUE_ID, "season": start_year, "page": page},
        )
        items = data.get("response", [])
        if not items:
            break
        for item in items:
            p = item["player"]
            stats = (item.get("statistics") or [{}])[0]
            games = stats.get("games", {})
            position_raw = games.get("position", "Midfielder")
            position = _SPORTS_POSITION_MAP.get(position_raw, "MID")
            team_id = stats.get("team", {}).get("id")
            await conn.execute(
                """
                INSERT INTO players (
                    season_id, fpl_id, team_fpl_id, first_name, second_name,
                    web_name, position
                ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT (season_id, fpl_id) DO NOTHING
                """,
                season_id,
                p["id"],
                team_id or 0,
                (p["name"].split(" ")[0] if " " in p["name"] else p["name"]),
                (" ".join(p["name"].split(" ")[1:]) if " " in p["name"] else ""),
                p.get("name", ""),
                position,
            )
            players_map[p["id"]] = {"position": position, "team_id": team_id}

        paging = data.get("paging", {})
        if page >= paging.get("total", 1):
            break
        page += 1
        await asyncio.sleep(0.5)  # respect rate limits

    log.info("upserted %d players for %s", len(players_map), label)

    # 5 — Per-fixture player stats (the core fact table)
    # Use a semaphore to limit concurrency — API-Sports rate limit is per-minute not per-day
    sem = asyncio.Semaphore(5)
    stats_count = 0

    async def fetch_fixture_stats(fixture_id: int) -> list[dict]:
        async with sem:
            try:
                data = await _sports_get(client, "/fixtures/players", {"fixture": fixture_id})
                await asyncio.sleep(0.2)
                return data.get("response", [])
            except Exception as e:
                log.warning("failed to fetch stats for fixture %d: %s", fixture_id, e)
                return []

    log.info("fetching per-fixture player stats for %d fixtures...", len(fixture_ids))
    results = await asyncio.gather(*[fetch_fixture_stats(fid) for fid in fixture_ids])

    for fixture_id, fixture_teams in zip(fixture_ids, results):
        for team_data in fixture_teams:
            team_id = team_data.get("team", {}).get("id")
            for player_data in team_data.get("players", []):
                p = player_data["player"]
                stats_list = player_data.get("statistics", [{}])
                s = stats_list[0] if stats_list else {}

                games = s.get("games", {})
                goals = s.get("goals", {})
                cards = s.get("cards", {})

                # Determine opponent
                fixture_row = await conn.fetchrow(
                    "SELECT home_team_fpl_id, away_team_fpl_id FROM fixtures "
                    "WHERE season_id=$1 AND fpl_id=$2",
                    season_id,
                    fixture_id,
                )
                if not fixture_row:
                    continue
                is_home = fixture_row["home_team_fpl_id"] == team_id
                opponent_id = (
                    fixture_row["away_team_fpl_id"] if is_home else fixture_row["home_team_fpl_id"]
                )

                try:
                    await conn.execute(
                        """
                        INSERT INTO gw_player_stats (
                            season_id, player_fpl_id, gw_number, fixture_fpl_id,
                            opponent_team_fpl_id, was_home,
                            minutes, goals_scored, assists, saves,
                            yellow_cards, red_cards, starts, total_points
                        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                        ON CONFLICT (season_id, player_fpl_id, fixture_fpl_id) DO UPDATE SET
                            minutes = EXCLUDED.minutes,
                            goals_scored = EXCLUDED.goals_scored,
                            assists = EXCLUDED.assists,
                            saves = EXCLUDED.saves,
                            yellow_cards = EXCLUDED.yellow_cards,
                            red_cards = EXCLUDED.red_cards,
                            starts = EXCLUDED.starts
                        """,
                        season_id,
                        p["id"],
                        None,  # gw_number — API-Sports uses fixture round, filled separately
                        fixture_id,
                        opponent_id,
                        is_home,
                        games.get("minutes") or 0,
                        goals.get("total") or 0,
                        goals.get("assists") or 0,
                        s.get("goalkeeper", {}).get("saves") or 0,
                        cards.get("yellow") or 0,
                        cards.get("red") or 0,
                        1 if games.get("lineups") else 0,
                        0,  # total_points — API-Sports doesn't have FPL points
                    )
                    stats_count += 1
                except Exception as e:
                    log.warning("failed to insert stat row: %s", e)

    log.info("upserted %d player-fixture stat rows for %s", stats_count, label)


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------


async def run_snapshot(conn: asyncpg.Connection) -> None:
    """Hourly: refresh players/teams/gameweeks/fixtures from FPL API."""
    log.info("=== SNAPSHOT: fetching FPL bootstrap + fixtures ===")
    async with httpx.AsyncClient(timeout=30.0) as client:
        bootstrap = await _fpl_get(client, "/bootstrap-static/")
        all_fixtures = await _fpl_get(client, "/fixtures/")

    season_id = await upsert_current_season(conn, bootstrap)
    await upsert_teams(conn, season_id, bootstrap)
    await upsert_gameweeks(conn, season_id, bootstrap)
    await upsert_players(conn, season_id, bootstrap)
    await upsert_fixtures_fpl(conn, season_id, all_fixtures)
    log.info("=== SNAPSHOT complete ===")


async def run_gw_update(conn: asyncpg.Connection) -> None:
    """Post-gameweek: update gw_player_stats for all players."""
    log.info("=== GW UPDATE: fetching player GW histories ===")
    async with httpx.AsyncClient(timeout=30.0) as client:
        bootstrap = await _fpl_get(client, "/bootstrap-static/")

    season_id = await conn.fetchval("SELECT id FROM seasons WHERE is_current = TRUE LIMIT 1")
    if not season_id:
        season_id = await upsert_current_season(conn, bootstrap)

    players = bootstrap["elements"]
    total = 0
    sem = asyncio.Semaphore(20)

    async def fetch_and_upsert(player: dict) -> int:
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=20.0) as c:
                    data = await _fpl_get(c, f"/element-summary/{player['id']}/")
                history = data.get("history", [])
                return await upsert_gw_stats_fpl(conn, season_id, player["id"], history)
            except Exception as e:
                log.warning("failed for player %d: %s", player["id"], e)
                return 0

    counts = await asyncio.gather(*[fetch_and_upsert(p) for p in players])
    total = sum(counts)
    log.info("=== GW UPDATE complete: %d stat rows upserted ===", total)


async def run_full(conn: asyncpg.Connection) -> None:
    """Full refresh: snapshot + GW stats."""
    await run_snapshot(conn)
    await run_gw_update(conn)


async def run_backfill(conn: asyncpg.Connection) -> None:
    """One-time: backfill all historical seasons from API-Sports."""
    log.info("=== BACKFILL: importing historical seasons from API-Sports ===")
    async with httpx.AsyncClient(timeout=60.0) as client:
        for start_year, label in _BACKFILL_SEASONS.items():
            await backfill_season(conn, client, start_year, label)
            await asyncio.sleep(2)  # be respectful between seasons
    log.info("=== BACKFILL complete ===")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description="Gaffer V2 ETL pipeline")
    parser.add_argument(
        "--mode",
        choices=["snapshot", "gw", "full", "backfill"],
        default="full",
        help="snapshot=hourly refresh | gw=post-gameweek stats | full=both | backfill=historical",
    )
    parser.add_argument(
        "--season",
        type=int,
        choices=list(_BACKFILL_SEASONS.keys()),
        help="backfill mode only: run a single season (e.g. --season 2023 for 2023/24). "
        "Omit to backfill all seasons.",
    )
    args = parser.parse_args()

    conn = await get_conn()
    try:
        if args.mode == "snapshot":
            await run_snapshot(conn)
        elif args.mode == "gw":
            await run_gw_update(conn)
        elif args.mode == "full":
            await run_full(conn)
        elif args.mode == "backfill":
            if args.season:
                label = _BACKFILL_SEASONS[args.season]
                async with httpx.AsyncClient(timeout=60.0) as client:
                    await backfill_season(conn, client, args.season, label)
            else:
                await run_backfill(conn)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
