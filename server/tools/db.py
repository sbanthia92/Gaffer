"""
V2 database query tool — Claude generates SQL, we execute it read-only.

Safety layers:
  1. Keyword blocklist rejects obviously destructive SQL before hitting the DB
  2. The gaffer_readonly DB user has SELECT-only grants — writes fail at connection level
  3. statement_timeout prevents runaway queries
"""

import re

import asyncpg

from server.config import settings

_BANNED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE"
    r"|EXEC|EXECUTE|pg_read_file|COPY)\b",
    re.IGNORECASE,
)
_MAX_ROWS = 50
_TIMEOUT_MS = 10_000

TOOL_DEFINITION = {
    "name": "query_database",
    "description": (
        "Execute a read-only SQL SELECT query against the FPL PostgreSQL database. "
        "Use this for any historical or analytical question: player form over past gameweeks, "
        "stats vs a specific opponent, season aggregates, xG/xA trends, "
        "double/blank gameweek detection, and cross-season comparisons.\n\n"
        "DATABASE SCHEMA:\n\n"
        "TABLE: seasons (id, label, start_year, is_current)\n"
        "  label: e.g. '2025/26'. is_current=TRUE is the live season.\n\n"
        "TABLE: teams (id, season_id, fpl_id, name, short_name, strength,\n"
        "  strength_attack_home, strength_attack_away, strength_defence_home, strength_defence_away)\n"  # noqa: E501
        "  fpl_id matches opponent_team_fpl_id in gw_player_stats.\n\n"
        "TABLE: players (id, season_id, fpl_id, team_fpl_id, first_name, second_name,\n"
        "  web_name, position, now_cost, total_points, minutes, goals_scored, assists,\n"
        "  clean_sheets, goals_conceded, yellow_cards, red_cards, bonus, form,\n"
        "  points_per_game, selected_by_percent, status, news, ict_index,\n"
        "  expected_goals, expected_assists, expected_goal_involvements,\n"
        "  creativity, influence, threat, updated_at)\n"
        "  web_name = short FPL name (Salah, Haaland). position: GKP/DEF/MID/FWD.\n"
        "  now_cost in tenths of £1m: 140 = £14.0m. Divide by 10.0 in SELECT.\n"
        "  status: 'a'=available, 'i'=injured, 'd'=doubtful, 's'=suspended.\n\n"
        "TABLE: gameweeks (id, season_id, gw_number, name, deadline_time,\n"
        "  average_entry_score, highest_score, is_current, is_next, is_finished)\n"
        "  gw_number 1–38. is_current=TRUE = live gameweek.\n\n"
        "TABLE: fixtures (id, season_id, fpl_id, gw_number, kickoff_time,\n"
        "  home_team_fpl_id, away_team_fpl_id, home_score, away_score, finished,\n"
        "  home_team_difficulty, away_team_difficulty)\n"
        "  gw_number is NULL for postponed fixtures.\n"
        "  difficulty 1=easy 5=hard. DGW = team appears twice in same gw_number.\n\n"
        "TABLE: gw_player_stats (id, season_id, player_fpl_id, gw_number, fixture_fpl_id,\n"
        "  opponent_team_fpl_id, was_home, minutes, goals_scored, assists, clean_sheets,\n"
        "  goals_conceded, own_goals, yellow_cards, red_cards, saves, bonus, bps,\n"
        "  total_points, value, transfers_in, transfers_out, starts,\n"
        "  influence, creativity, threat, ict_index,\n"
        "  expected_goals, expected_assists, expected_goal_involvements, expected_goals_conceded)\n"
        "  One row per player per fixture. DGW = two rows for same gw_number.\n"
        "  total_points = FPL points that fixture. starts=1 if started, 0 if sub.\n"
        "  value = price that GW in tenths of £1m.\n\n"
        "COMMON PATTERNS:\n"
        "  Current season:  JOIN seasons s ON p.season_id=s.id WHERE s.is_current=TRUE\n"
        "  Player search:   WHERE p.web_name ILIKE '%salah%'\n"
        "  Opponent join:   JOIN teams t ON g.opponent_team_fpl_id=t.fpl_id AND g.season_id=t.season_id\n"  # noqa: E501
        "  Recent form:     ORDER BY gw_number DESC LIMIT 5\n"
        "  H2H vs team:     WHERE g.opponent_team_fpl_id = (SELECT fpl_id FROM teams WHERE season_id=s.id AND short_name ILIKE '%che%')\n"  # noqa: E501
        "  Price in £m:     ROUND(now_cost / 10.0, 1) AS price_millions\n\n"
        "RULES:\n"
        "  1. Always filter by season. Default to is_current=TRUE unless comparing seasons.\n"
        "  2. Filter starts=1 to exclude bench cameos from form analysis.\n"
        "  3. LIMIT to 20 rows unless more are genuinely needed.\n"
        "  4. SELECT only the columns needed — never SELECT *.\n"
        "  5. Only SELECT statements are permitted."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": (
                    "A read-only SQL SELECT statement. "
                    "Must start with SELECT. No INSERT/UPDATE/DELETE/DROP. "
                    "Always include a season filter. LIMIT results."
                ),
            }
        },
        "required": ["sql"],
    },
}


async def execute(sql: str) -> dict:
    """Execute a read-only SQL query and return results as a list of dicts."""
    sql = sql.strip()

    if _BANNED.search(sql):
        return {"error": True, "message": "Query blocked: only SELECT statements are permitted."}

    if not sql.upper().startswith("SELECT"):
        return {"error": True, "message": "Query blocked: must begin with SELECT."}

    if not settings.database_url:
        return {"error": True, "message": "Database not configured (DATABASE_URL missing)."}

    try:
        conn = await asyncpg.connect(settings.database_url)
        try:
            await conn.execute(f"SET statement_timeout = {_TIMEOUT_MS}")
            rows = await conn.fetch(sql)
        finally:
            await conn.close()
    except asyncpg.PostgresError as e:
        return {"error": True, "message": f"Database error: {e}"}
    except Exception as e:
        return {"error": True, "message": f"Query failed: {e}"}

    if not rows:
        return {"rows": [], "row_count": 0}

    result = [dict(row) for row in rows[:_MAX_ROWS]]
    return {
        "rows": result,
        "row_count": len(result),
        "truncated": len(rows) > _MAX_ROWS,
    }
