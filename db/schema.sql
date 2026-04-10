-- =============================================================================
-- THE GAFFER V2 — POSTGRESQL SCHEMA
-- =============================================================================
-- Design principles:
--   1. Every table and column is commented so Claude understands what it holds
--      when generating SQL via the query_database tool.
--   2. FPL API field names preserved where possible (fpl_id, web_name, etc.)
--      so ETL mapping is obvious and Claude's generated SQL is predictable.
--   3. All monetary values stored as integers in tenths of £1m.
--      e.g. now_cost = 85 means £8.5m. Divide by 10.0 in SELECT for £m values.
--   4. All joins between fact/dimension tables use (season_id, fpl_id) pairs
--      rather than surrogate PKs — ETL never needs to look up internal IDs.
--   5. All inserts are upserts (ON CONFLICT DO UPDATE) — ETL is idempotent.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- seasons
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seasons (
    id          SERIAL PRIMARY KEY,
    label       TEXT    NOT NULL UNIQUE,            -- e.g. '2025/26'
    start_year  INT     NOT NULL,                   -- e.g. 2025
    is_current  BOOLEAN NOT NULL DEFAULT FALSE,     -- only one row TRUE at a time
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE seasons IS
    'One row per Premier League season. is_current=TRUE marks the live season. '
    'Use WHERE s.is_current = TRUE to scope queries to the current season.';
COMMENT ON COLUMN seasons.label IS
    'Human-readable season string, e.g. ''2025/26''. Always include in responses.';
COMMENT ON COLUMN seasons.is_current IS
    'TRUE for the active season only. Always filter by this unless comparing across seasons.';

-- Only one current season at a time
CREATE UNIQUE INDEX IF NOT EXISTS idx_seasons_current
    ON seasons (is_current) WHERE is_current = TRUE;


-- ---------------------------------------------------------------------------
-- teams
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS teams (
    id                      SERIAL PRIMARY KEY,
    season_id               INT  NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    fpl_id                  INT  NOT NULL,   -- teams[].id from /bootstrap-static/
    name                    TEXT NOT NULL,   -- e.g. 'Manchester City'
    short_name              TEXT NOT NULL,   -- 3-char abbreviation, e.g. 'MCI'
    strength                INT,             -- FPL overall strength 1–5
    strength_attack_home    INT,
    strength_attack_away    INT,
    strength_defence_home   INT,
    strength_defence_away   INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (season_id, fpl_id)
);

COMMENT ON TABLE teams IS
    'Premier League clubs per season. fpl_id matches team ids in fixtures and gw_player_stats. '
    'Join via: JOIN teams t ON g.opponent_team_fpl_id = t.fpl_id AND g.season_id = t.season_id';
COMMENT ON COLUMN teams.fpl_id IS
    'Team ID from FPL /bootstrap-static/ teams[].id. Used as FK in fixtures and gw_player_stats.';
COMMENT ON COLUMN teams.short_name IS
    '3-letter abbreviation, e.g. MCI, LIV, ARS, CHE. Use ILIKE for fuzzy team search.';
COMMENT ON COLUMN teams.strength IS
    'FPL overall strength rating 1–5. Higher = stronger. Useful for fixture difficulty context.';

CREATE INDEX IF NOT EXISTS idx_teams_season     ON teams (season_id);
CREATE INDEX IF NOT EXISTS idx_teams_season_fpl ON teams (season_id, fpl_id);


-- ---------------------------------------------------------------------------
-- players
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS players (
    id              SERIAL PRIMARY KEY,
    season_id       INT  NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    fpl_id          INT  NOT NULL,   -- elements[].id from /bootstrap-static/
    team_fpl_id     INT  NOT NULL,   -- current team fpl_id (references teams.fpl_id)
    first_name      TEXT NOT NULL,
    second_name     TEXT NOT NULL,
    web_name        TEXT NOT NULL,   -- short FPL display name, e.g. 'Salah', 'Haaland'
    position        TEXT NOT NULL CHECK (position IN ('GKP', 'DEF', 'MID', 'FWD')),
    -- Season snapshot — updated by ETL on every run
    now_cost            INT,             -- current price, tenths of £1m (85 = £8.5m)
    start_cost          INT,             -- price at start of season
    total_points        INT,             -- cumulative FPL points this season
    minutes             INT,             -- total minutes played this season
    goals_scored        INT,
    assists             INT,
    clean_sheets        INT,
    goals_conceded      INT,
    yellow_cards        INT,
    red_cards           INT,
    bonus               INT,             -- total bonus points this season
    form                NUMERIC(4,1),    -- FPL rolling form (last 4 GWs)
    points_per_game     NUMERIC(4,2),
    selected_by_percent NUMERIC(5,2),   -- % of FPL managers who own this player
    transfers_in_event  INT,            -- transfers in this GW
    transfers_out_event INT,
    status              TEXT,            -- 'a' available, 'i' injured, 'd' doubtful, 's' suspended, 'u' unavailable
    chance_of_playing_next_round INT,   -- 0–100, null if fully available
    news                TEXT,           -- latest injury/suspension news
    creativity          NUMERIC(6,1),
    influence           NUMERIC(6,1),
    threat              NUMERIC(6,1),
    ict_index           NUMERIC(6,1),   -- composite ICT score
    expected_goals              NUMERIC(6,2),
    expected_assists            NUMERIC(6,2),
    expected_goal_involvements  NUMERIC(6,2),
    photo               TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (season_id, fpl_id)
);

COMMENT ON TABLE players IS
    'One row per player per season. Snapshot columns (price, form, status) updated each ETL run. '
    'Use web_name for player lookup (ILIKE). Prices are in tenths of £1m: divide by 10.0 for £m. '
    'position values: GKP, DEF, MID, FWD. '
    'status: ''a''=available, ''i''=injured, ''d''=doubtful, ''s''=suspended, ''u''=unavailable.';
COMMENT ON COLUMN players.fpl_id IS
    'FPL element id from /bootstrap-static/ elements[].id. '
    'Matches player_fpl_id in gw_player_stats.';
COMMENT ON COLUMN players.web_name IS
    'Short display name used on the FPL site, e.g. Salah, Haaland, Alexander-Arnold. '
    'Use this for player search: WHERE p.web_name ILIKE ''%salah%''';
COMMENT ON COLUMN players.now_cost IS
    'Current price in tenths of £1m. Example: 140 = £14.0m. '
    'In SELECT, use: ROUND(now_cost / 10.0, 1) AS price_millions';
COMMENT ON COLUMN players.form IS
    'FPL rolling average score over last 4 gameweeks. Higher = better recent form.';
COMMENT ON COLUMN players.selected_by_percent IS
    'Percentage of all FPL managers who own this player. High = template/popular pick.';
COMMENT ON COLUMN players.ict_index IS
    'FPL Influence-Creativity-Threat composite score. Higher = more attacking involvement.';
COMMENT ON COLUMN players.status IS
    'Player availability: ''a''=available, ''i''=injured, ''d''=doubtful, '
    '''s''=suspended, ''u''=unavailable. Filter with: WHERE status = ''a''';

CREATE INDEX IF NOT EXISTS idx_players_season      ON players (season_id);
CREATE INDEX IF NOT EXISTS idx_players_season_fpl  ON players (season_id, fpl_id);
CREATE INDEX IF NOT EXISTS idx_players_team        ON players (season_id, team_fpl_id);
CREATE INDEX IF NOT EXISTS idx_players_position    ON players (season_id, position);
CREATE INDEX IF NOT EXISTS idx_players_web_name_trgm ON players USING gin (web_name gin_trgm_ops);


-- ---------------------------------------------------------------------------
-- gameweeks
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gameweeks (
    id                          SERIAL PRIMARY KEY,
    season_id                   INT  NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    gw_number                   INT  NOT NULL,   -- 1–38
    name                        TEXT NOT NULL,   -- e.g. 'Gameweek 14'
    deadline_time               TIMESTAMPTZ,
    average_entry_score         INT,             -- avg FPL score across all managers
    highest_score               INT,
    most_selected_fpl_id        INT,             -- fpl_id of most selected player
    most_transferred_in_fpl_id  INT,
    top_element_fpl_id          INT,             -- fpl_id of top scoring player that GW
    top_element_points          INT,
    is_current                  BOOLEAN NOT NULL DEFAULT FALSE,
    is_next                     BOOLEAN NOT NULL DEFAULT FALSE,
    is_finished                 BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (season_id, gw_number)
);

COMMENT ON TABLE gameweeks IS
    'FPL gameweek metadata per season. '
    'Use is_current=TRUE to find the live gameweek. '
    'Use is_finished=TRUE to filter completed gameweeks. '
    'average_entry_score is useful for context: a player outperforming this was impactful.';
COMMENT ON COLUMN gameweeks.gw_number IS
    'Gameweek number 1–38. Use in queries: WHERE gw_number BETWEEN 10 AND 15.';
COMMENT ON COLUMN gameweeks.average_entry_score IS
    'Average FPL score across all managers for this gameweek. '
    'A player earning more than this had a positive GW impact.';

CREATE INDEX IF NOT EXISTS idx_gameweeks_season   ON gameweeks (season_id);
CREATE INDEX IF NOT EXISTS idx_gameweeks_current  ON gameweeks (season_id, is_current);
CREATE INDEX IF NOT EXISTS idx_gameweeks_gw       ON gameweeks (season_id, gw_number);


-- ---------------------------------------------------------------------------
-- fixtures
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fixtures (
    id                  SERIAL PRIMARY KEY,
    season_id           INT  NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    fpl_id              INT  NOT NULL,   -- fixture id from FPL API
    gw_number           INT,             -- NULL if postponed/not yet scheduled
    kickoff_time        TIMESTAMPTZ,
    home_team_fpl_id    INT  NOT NULL,
    away_team_fpl_id    INT  NOT NULL,
    home_score          INT,             -- NULL until played
    away_score          INT,
    finished            BOOLEAN NOT NULL DEFAULT FALSE,
    started             BOOLEAN NOT NULL DEFAULT FALSE,
    home_team_difficulty INT,            -- FPL difficulty for home team (1=easy, 5=hard)
    away_team_difficulty INT,            -- FPL difficulty for away team (1=easy, 5=hard)
    minutes             INT DEFAULT 0,
    provisional_start_time BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (season_id, fpl_id)
);

COMMENT ON TABLE fixtures IS
    'Every Premier League fixture per season. '
    'IMPORTANT: gw_number is NULL for postponed/rescheduled matches — '
    'this is the FPL API event=null issue that causes incorrect DGW/BGW detection. '
    'To detect double gameweeks: COUNT fixtures per team per gw_number > 1. '
    'To detect blank gameweeks: a team has no fixtures for a given gw_number. '
    'home_team_difficulty and away_team_difficulty are 1 (easiest) to 5 (hardest).';
COMMENT ON COLUMN fixtures.gw_number IS
    'Gameweek this fixture belongs to. NULL = postponed or not yet scheduled. '
    'A team appearing twice in the same gw_number has a double gameweek (DGW). '
    'A team not appearing in a gw_number has a blank gameweek (BGW).';
COMMENT ON COLUMN fixtures.home_team_difficulty IS
    'FPL fixture difficulty for the home team: 1=easiest, 5=hardest. '
    'Low score = favourable fixture for the home side.';
COMMENT ON COLUMN fixtures.away_team_difficulty IS
    'FPL fixture difficulty for the away team: 1=easiest, 5=hardest. '
    'Low score = favourable fixture for the away side.';

CREATE INDEX IF NOT EXISTS idx_fixtures_season    ON fixtures (season_id);
CREATE INDEX IF NOT EXISTS idx_fixtures_gw        ON fixtures (season_id, gw_number);
CREATE INDEX IF NOT EXISTS idx_fixtures_home      ON fixtures (season_id, home_team_fpl_id);
CREATE INDEX IF NOT EXISTS idx_fixtures_away      ON fixtures (season_id, away_team_fpl_id);


-- ---------------------------------------------------------------------------
-- gw_player_stats
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gw_player_stats (
    id                  SERIAL PRIMARY KEY,
    season_id           INT  NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    player_fpl_id       INT  NOT NULL,   -- references players.fpl_id (same season_id)
    gw_number           INT  NOT NULL,   -- 1–38
    fixture_fpl_id      INT  NOT NULL,   -- references fixtures.fpl_id (same season_id)
    opponent_team_fpl_id INT NOT NULL,   -- references teams.fpl_id (same season_id)
    was_home            BOOLEAN NOT NULL,
    -- Match scores
    team_h_score        INT,
    team_a_score        INT,
    -- Core stats
    minutes             INT  NOT NULL DEFAULT 0,
    goals_scored        INT  NOT NULL DEFAULT 0,
    assists             INT  NOT NULL DEFAULT 0,
    clean_sheets        INT  NOT NULL DEFAULT 0,
    goals_conceded      INT  NOT NULL DEFAULT 0,
    own_goals           INT  NOT NULL DEFAULT 0,
    penalties_saved     INT  NOT NULL DEFAULT 0,
    penalties_missed    INT  NOT NULL DEFAULT 0,
    yellow_cards        INT  NOT NULL DEFAULT 0,
    red_cards           INT  NOT NULL DEFAULT 0,
    saves               INT  NOT NULL DEFAULT 0,
    bonus               INT  NOT NULL DEFAULT 0,   -- 0, 1, 2, or 3
    bps                 INT  NOT NULL DEFAULT 0,   -- raw Bonus Points System score
    total_points        INT  NOT NULL DEFAULT 0,   -- final FPL points this GW
    -- Ownership and price at time of this GW
    value               INT,    -- price that GW in tenths of £1m
    selected            INT,    -- number of FPL managers who had this player
    transfers_in        INT,
    transfers_out       INT,
    transfers_balance   INT,
    -- Advanced metrics
    influence           NUMERIC(6,1),
    creativity          NUMERIC(6,1),
    threat              NUMERIC(6,1),
    ict_index           NUMERIC(6,1),
    expected_goals              NUMERIC(6,2),
    expected_assists            NUMERIC(6,2),
    expected_goal_involvements  NUMERIC(6,2),
    expected_goals_conceded     NUMERIC(6,2),
    starts              INT,    -- 1 if started, 0 if came off bench
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (season_id, player_fpl_id, fixture_fpl_id)
);

COMMENT ON TABLE gw_player_stats IS
    'Core fact table — one row per player per gameweek fixture. '
    'PRIMARY USE: form analysis, H2H vs opponent, season aggregates, xG/xA trends. '
    'Double gameweek: a player has TWO rows for the same gw_number (one per fixture). '
    'Always join to players for web_name, to teams for opponent name. '
    'Filter starts=1 to exclude bench appearances from form analysis.';
COMMENT ON COLUMN gw_player_stats.total_points IS
    'Final FPL points earned in this fixture. For double GWs, SUM both rows for total GW score.';
COMMENT ON COLUMN gw_player_stats.starts IS
    '1 if the player started, 0 if substitute. '
    'Use WHERE starts = 1 for accurate form analysis excluding cameos.';
COMMENT ON COLUMN gw_player_stats.value IS
    'Player price at the time of this gameweek in tenths of £1m. '
    'Tracks price changes across the season.';
COMMENT ON COLUMN gw_player_stats.bps IS
    'Raw Bonus Points System score. Top 3 BPS scorers per match earn 3/2/1 bonus points.';
COMMENT ON COLUMN gw_player_stats.expected_goals IS
    'Expected goals (xG) this fixture. Better predictor of future scoring than actual goals.';
COMMENT ON COLUMN gw_player_stats.expected_goal_involvements IS
    'xG + xA for this fixture. Key metric for attacking players — measures underlying quality.';
COMMENT ON COLUMN gw_player_stats.was_home IS
    'TRUE if player''s team was the home side. Use for home/away performance splits.';

CREATE INDEX IF NOT EXISTS idx_gws_player_season  ON gw_player_stats (season_id, player_fpl_id);
CREATE INDEX IF NOT EXISTS idx_gws_player_gw      ON gw_player_stats (season_id, player_fpl_id, gw_number);
CREATE INDEX IF NOT EXISTS idx_gws_gw_number      ON gw_player_stats (season_id, gw_number);
CREATE INDEX IF NOT EXISTS idx_gws_opponent       ON gw_player_stats (season_id, opponent_team_fpl_id);
CREATE INDEX IF NOT EXISTS idx_gws_fixture        ON gw_player_stats (season_id, fixture_fpl_id);
-- Most common query: recent form for a player, newest GWs first
CREATE INDEX IF NOT EXISTS idx_gws_player_gw_desc ON gw_player_stats (season_id, player_fpl_id, gw_number DESC);


-- ---------------------------------------------------------------------------
-- Extensions (run once by DBA — safe to re-run)
-- ---------------------------------------------------------------------------
-- Enables trigram fuzzy search on player web_name (used by idx_players_web_name_trgm)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
