# Changelog

All notable changes to The Gaffer are documented here.

## [0.77.0] — 2026-07-30

### Fixed
- **`gaffer_readonly` was missing `SELECT` on sequences** — the newly-shipped nightly DB backup (`pg_dump` via `DATABASE_URL`) failed on its first real run with `permission denied for sequence fixtures_id_seq`. Table `SELECT` doesn't imply sequence `SELECT`; `pg_dump` reads every identity column's backing sequence. Granted on prod, plus `ALTER DEFAULT PRIVILEGES` so future tables' sequences inherit it automatically.
- **`backup_db.py` swallowed `pg_dump`'s stderr** — a failure only surfaced a generic "non-zero exit status" with no indication of *why*, which is why the above required an SSH session and a manual re-run to diagnose. Now captures and surfaces stderr in the raised error.

## [0.76.0] — 2026-07-30

### Added
- **Nightly automated DB backups** — `pipeline/backup_db.py` runs `pg_dump` against `DATABASE_URL` (read-only role), gzips the output, and uploads to a new private S3 bucket (`gaffer-db-backups-<account-id>`, 30-day lifecycle expiration). Scheduled 02:15 UTC daily via `scripts/setup_cron.sh`. EBS survives reboots but not instance replacement, so this closes that durability gap without a full RDS migration.

## [0.75.0] — 2026-07-30

### Fixed
- **EC2 AMI was unpinned** — `terraform/main.tf` looked up the latest Amazon Linux 2023 AMI via `most_recent = true` on every plan/apply. AWS had published a newer AMI since the instance was created, so the next `terraform apply` would have force-replaced the running production instance (new instance, new root EBS volume, all Postgres data gone). AMI is now pinned via `var.ec2_ami_id`, defaulting to the currently-running AMI. Bumping it is now a deliberate, documented action.

## [0.74.0] — 2026-07-30

### Fixed
- **CloudWatch ETL heartbeat permission** — `gaffer-ec2-role` was missing `cloudwatch:PutMetricData`, so the hourly ETL snapshot's heartbeat metric (`Gaffer/ETL` namespace) has been silently failing on every run since it was added. Added a scoped IAM statement for that one namespace.

## [0.73.0] — 2026-05-20

### Fixed
- **FDR perspective in `get_team_all_fixtures`** — was returning both `home_difficulty` and `away_difficulty`, leaving Claude to guess which applied. Now returns a single `difficulty` field from the queried team's perspective (home FDR when the team plays at home, away FDR when they travel).
- **Silent blank responses on errors** — if `_generate()` threw an exception mid-stream, the UI would silently show nothing. Generator is now wrapped in a try/except that yields a user-facing error message.
- **3-player club limit enforced in system prompt** — FPL's hard 3-player-per-club rule was not stated anywhere in Claude's instructions, allowing it to suggest a fourth player from the same team. Rule is now explicit: count the user's existing squad members per club before suggesting transfers.
- **FDR 5 fixture warning on transfer suggestions** — Claude was suggesting players with FDR 5 next fixtures without flagging the difficulty. New FIXTURE DIFFICULTY RULE in the system prompt requires Claude to lead with a warning if the candidate's very next fixture is FDR 5.

## [0.72.0] — 2026-05-14

### Changed
- **Historical context feature card** — updated mockup query from "How has Salah performed against Arsenal historically?" to "How did Haaland perform against Arsenal in the reverse fixture?" to accurately reflect current-season per-fixture capability. Updated desc from "3 seasons of match-by-match stats" (inaccurate — historical data is season-level totals only) to clarify GW-by-GW is current season only.

## [0.71.0] — 2026-05-13

### Fixed
- **Players backfill INSERT** — removed five columns (`own_goals`, `penalties_saved`, `penalties_missed`, `saves`, `bps`) that exist in the FPL `history_past` response but not in the `players` table, causing an `UndefinedColumnError` on every backfill run. The INSERT now only includes the 8 stat columns that actually exist in the schema.

## [0.70.0] — 2026-05-13

### Changed
- **Historical backfill now uses FPL `history_past`** — replaced the broken API-Sports backfill (which referenced `settings.api_sports_key`, a field that was never defined in `Settings`, so it would crash on any `--mode=backfill` run) with a pure-FPL implementation. Each player's `/element-summary/{id}/history_past` provides season-level totals (goals, assists, points, minutes, clean sheets, etc.) for all past seasons. These are upserted into the `players` table so historical season stats are queryable. No third-party API key required. Limitation: per-fixture `gw_player_stats` data is not available for past seasons via FPL — `get_player_vs_opponent` remains current-season-only.

### Removed
- All API-Sports code removed from `pipeline/etl_v2.py`: `_SPORTS_BASE`, `_PL_LEAGUE_ID`, `_BACKFILL_SEASONS`, `_SPORTS_POSITION_MAP`, `_sports_get()`, `backfill_season()`. The `--season` CLI argument is also removed (the FPL backfill always covers all seasons found in `history_past`).

## [0.69.0] — 2026-05-13

### Fixed
- **Hero STARTING XI restored to 11 players** and **chat mockup copy restored to DATA/REASONING format** — both were lost when PR #158's squash-merge (cut from a stale base) reached main after PR #153/#156. The fix from PR #162 only covered the first commit; this re-applies the second commit that was added after the merge.

## [0.68.0] — 2026-05-13

### Fixed
- **`get_player_vs_opponent` cross-season data** — the historical backfill uses API-Sports player/team IDs while the current season uses FPL IDs; querying by ID directly only returned current-season rows. Fixed by joining through the `players` and `teams` tables by name within each season's own ID system, so all three seasons of historical data are searched correctly.

## [0.67.0] — 2026-05-13

### Fixed
- **Re-apply stale UI string removals** — PR #158 was squash-merged from a branch cut before #155 landed, silently reintroducing three UI strings that had already been removed. Re-applies: removal of both "The Dressing Room · Live" topbar chips, removal of the "Fanzine · Issue 27" hero sticker, and corrects the press feature description from "BBC Sport and Sky Sports" to "The Guardian".

## [0.66.0] — 2026-05-13

### Added
- **Job run metrics** — `pipeline/job_metrics.py` records every attempt, success, and failure from the two EC2 cron jobs (`press_ingest`, `gw_check`) into a new `job_runs` PostgreSQL table. Both `pipeline/run_press_ingest.py` and `pipeline/check_gw_complete.py` are instrumented; `gw_check` records `action: skipped | synced` in `details` so silent "nothing to do" runs are distinguishable from real GW syncs.
- **`/admin/jobs` endpoint** — new admin-auth-gated endpoint returning job health (last run time, status, duration, 7-day pass rate per job), Postgres row counts (players, finished gameweeks, GW stat rows, seasons), and Pinecone namespace vector counts.
- **Admin dashboard: Background Jobs section** — table showing last-run time, status dot (green/red), duration, and 7-day pass rate for each cron job. Pass rate below 90% highlights in amber.
- **Admin dashboard: Data Stores section** — metric cards for current-season player count, finished gameweeks, GW stat rows, seasons in DB, total Pinecone vectors, and a card per Pinecone namespace.
- **`db/migrations/001_job_runs.sql`** — migration file; apply once on the existing EC2 DB with `psql $DATABASE_ETL_URL -f db/migrations/001_job_runs.sql`.

### Changed
- `pipeline/check_gw_complete.py` now imports `server.config` for secrets injection so it runs correctly in production mode (same pattern as `run_press_ingest.py`).

## [0.65.0] — 2026-05-13

### Removed
- **`ingest.yml` GitHub Actions workflow deleted** — the workflow was broken (`pipeline.ingest_press` module was removed in v0.57.0) and duplicated work already handled by EC2 cron jobs running press ingestion twice daily at 07:00 and 19:00 UTC.

## [0.64.0] — 2026-05-11

### Added
- **Dynamic GW-triggered ETL** — new `pipeline/check_gw_complete.py` poller replaces the hardcoded Tuesday cron for post-gameweek DB sync. It fetches FPL bootstrap events each hour, compares the highest `finished=True` gameweek against a local state file (`pipeline/.last_synced_gw`), and only fires `etl_v2 --mode=gw` when a new gameweek has actually finished. This fixes double-gameweek weeks where some fixtures fall mid-week and the old Tuesday schedule either fired too early (before results were in) or missed them entirely. The EC2 cron in `scripts/setup_cron.sh` is updated accordingly.

## [0.63.0] — 2026-05-11

### Fixed
- **Removed stale odds and API-Sports references from landing page** — the "Live data" feature card still advertised "bookmaker odds pulled directly from API-Sports" and the example chat showed betting odds (match winner, BTTS, Over 2.5) and "to score" decimal odds for Salah/Haaland. `get_odds` and the API-Sports dependency were removed in v0.52.0; the copy now reflects the FPL-API-only data path. (Note: the broader mockup rewrite landed in v0.56.0; this entry covers the original targeted fix.)

## [0.62.0] — 2026-05-11

### Changed
- **Player names are now click-to-reveal links instead of inline chips** — player names mentioned in Claude's answers render as gold-underlined text links. Clicking one opens a small popover showing the full player card (photo, team, position, price, form, points, ownership, injury badge). The popover closes on outside click or Escape, and is clamped to stay within the viewport. This removes the inline chip layout that was breaking table alignment and interrupting reading flow.

## [0.61.0] — 2026-05-11

### Fixed
- **Removed placeholder "terrace fanzine" flavour text from production UI** — the topbar chip "The Dressing Room · Live" (in `ui/src/Landing.tsx` and `ui/src/App.tsx`) and the hero sticker "Fanzine · Issue 27" (in `ui/src/Landing.tsx`) were holdovers from the terrace-zine redesign that meant nothing to real users. Removed the markup and the now-orphaned `.landing-live-chip`, `.hero-sticker`, and `.chat-live-chip` CSS rules.

## [0.60.0] — 2026-05-11

### Changed
- **CLAUDE.md cleanup of stale API-Sports references** — removed the `_CURRENT_SEASON` note (the constant was deleted in v0.52.0 when API-Sports was removed; FPL tools now derive the season from live bootstrap data), corrected the FPL tool count from 17 to 15 (`search_team` and `get_odds` were removed in v0.52.0), and renamed the player-disambiguation gotcha to reference `search_players_by_criteria` (the actual current tool) instead of the non-existent `search_player`.

## [0.59.0] — 2026-05-11

### Fixed
- **Landing page "STARTING XI" team sheet only had 7 players** — a valid FPL starting XI is exactly 11 players. The decorative team sheet in `ui/src/Landing.tsx` now fields a realistic 4-3-3: Flekken; Alexander-Arnold, Saliba, Van Dijk, Pedro Porro; Salah, Palmer, Saka; Haaland, Isak, Watkins.

## [0.58.0] — 2026-05-11

### Fixed
- **`get_player_vs_opponent` missing season context** — the SQL query didn't JOIN the `seasons` table, so Claude received rows with just a `gw_number` and no year (e.g. "GW10" with no season). Added `JOIN seasons s ON g.season_id = s.id` and `s.label AS season` / `s.start_year` to the SELECT so each row is labelled (e.g. "2022/23 · GW38").
- **`get_player_vs_opponent` wrong cross-season ordering** — `ORDER BY g.gw_number DESC` ranked GW38 from an older season above GW1 from the current season. Fixed to `ORDER BY s.start_year DESC, g.gw_number DESC` so the most recent fixtures always surface first.

## [0.57.0] — 2026-05-11

### Fixed
- **Fixture difficulty columns stored swapped** — `upsert_fixtures_fpl` in `pipeline/etl_v2.py` wrote `team_a_difficulty` into `home_team_difficulty` and vice versa, based on an incorrect comment claiming the FPL API convention was reversed. In reality FPL's `team_h_difficulty` is the FDR for the home team and `team_a_difficulty` is the FDR for the away team. The swap corrupted clean-sheet probability inputs for `player_xpts`, so every CS-based xPts value was computed from the opponent's FDR instead of the player's team's FDR.

## [0.56.0] — 2026-05-11

### Changed
- **Feature mockup accuracy** — rewrote all 5 FEATURES chat mockups in `Landing.tsx` to match real Gaffer output: bold VERDICT first, DATA bullets with realistic numbers (pts, xGI, FDR, form), then REASONING. Removed odds, API-Sports references, and fabricated injury quotes that referenced removed tools (`search_team`, `get_odds`, bookmaker data). Updated feature descriptions to reflect FPL API (not API-Sports) and actual press sources (BBC Sport + The Guardian, not Sky Sports).

## [0.55.0] — 2026-05-11

### Fixed
- **`AttributeError: type object 'datetime.datetime' has no attribute 'UTC'` in ETL fallback** — `pipeline/etl_v2.py` imported `datetime` as the class but `_current_season_start_year` called `datetime.now(datetime.UTC)` in its fallback branch. `UTC` is a module-level constant in `datetime`, not a class attribute. Import `UTC` directly and pass it to `datetime.now()`. Only triggered when the FPL API bootstrap events array is empty/malformed, so it was a latent crash.

## [0.54.0] — 2026-05-11

### Fixed
- **Landing page press source attribution** — the "Press conference context" feature card on `ui/src/Landing.tsx` still credited "BBC Sport and Sky Sports press conferences" even though both feeds were retired (Sky Sports for paywall-empty descriptions in v0.46.0, BBC swapped out afterwards). The card now accurately attributes the source to The Guardian's Premier League coverage.

## [0.53.0] — 2026-05-11

### Fixed
- **`'team_id'` KeyError on team fixture queries** — the tool dispatch table in `main.py` still referenced `team_id`, `team1_id`, `team2_id` and the removed `search_team`/`get_odds` handlers after the API-Sports removal in v0.52.0. Updated to `team_name`/`team1_name`/`team2_name` to match the new FPL-based function signatures and tool definitions.

## [0.52.0] — 2026-05-11

### Changed
- **API-Sports dependency removed** — `get_fixtures`, `get_standings`, `get_team_recent_fixtures`, `get_head_to_head`, and `get_team_all_fixtures` now use the FPL API instead of api-sports.io. Standings are computed from completed FPL fixture results. `search_team` and `get_odds` removed entirely — tools that previously took numeric API-Sports IDs now take team names directly. `API_SPORTS_KEY` secret is no longer needed.

## [0.51.0] — 2026-05-11

### Fixed
- **CD always force-reinstalls sports-context-mcp** — `pip install -r requirements.txt` treats git-sourced packages as already satisfied even when the upstream repo has been updated, causing the old version to stay in the venv. The deploy step now runs a `--force-reinstall --no-deps` pass for the MCP package so EC2 always gets the latest server.py.

## [0.50.0] — 2026-05-11

### Changed
- **Terrace zine UI redesign** — complete visual overhaul to a bold "terrace fanzine / Panini sticker book" aesthetic. Anton headlines, cream halftone background (`--paper: #fff3df`), no border-radius, hard offset box-shadows, ink-black sidebar with gold accents, stat strip on landing, and rotated sticker chips throughout. Chat page gains a gold top bar, Anton empty-state headline, and a "Send ⚽" composer with red-shadow button.

## [0.49.0] — 2026-05-11

### Changed
- **Gaffer now consumes sports-context-mcp via MCP protocol** — historical stats (`query_historical_stats`) and press conference RAG (`query_press_conferences`) are now served by a subprocess running the sports-context-mcp server over stdio. Claude's `query_database` tool is removed; the MCP tools replace it. The DB connection pool is retained for FPL-specific tools (`get_player_stats`, `get_player_vs_opponent`, `get_player_xpts`) that use pre-packaged SQL queries.
- **RAG pre-fetch removed** — the old Pinecone `rag.py` module and its pre-fetch on every request are gone. Claude now calls `query_press_conferences` on demand when injury news or press context is relevant, reducing unnecessary token usage.
- **MCP session lifecycle** — the MCP subprocess is started once at app startup (FastAPI lifespan) and kept alive across all requests. Tool definitions from the MCP server are registered with Claude automatically at startup.

## [0.48.0] — 2026-05-11

### Changed
- **Press ingestion consolidated to sports-context-mcp** — `pipeline/ingest_press.py` removed. The cron job now runs `jobs.ingest_press_content` from the `sports-context-mcp` package, which covers BBC Sport RSS, The Guardian content API (full article body), and FPL player news in a single job. The Pinecone `press` namespace is unchanged.

## [0.47.0] — 2026-05-11

### Changed
- **`sports-context-mcp` extracted to standalone repo** — MCP server code (press conference queries, historical stats queries, press/match ingestion jobs) now lives at `https://github.com/sbanthia92/sports-context-mcp` and is referenced as an external dependency in `requirements.txt`. This keeps the Gaffer repo focused on the web app while the MCP server can be consumed independently by Claude Desktop or any MCP host.

## [0.46.0] — 2026-05-02

### Fixed
- **Sky Sports RSS replaced with The Guardian** — Sky Sports feed was returning 0 PL articles (empty description fields due to paywall). Replaced with The Guardian Premier League RSS feed which provides full article text.

## [0.45.0] — 2026-05-01

### Fixed
- **Pinecone monthly quota exhaustion** — player news vectors were accumulating on every ingest run because the document ID included `news_added` date; each status change created a new vector and old ones were never removed. Fixed by using a stable per-player ID so each run overwrites the existing vector in place.
- **Stale press articles never deleted** — RSS articles older than 14 days were sitting in Pinecone indefinitely, consuming storage and competing with fresh content. Ingest now deletes press articles older than 14 days via a metadata filter on `pub_timestamp` after each run.

## [0.44.0] — 2026-04-29

### Added
- **Expected Points (xPts) per player** — new `get_player_xpts` tool backed by a PostgreSQL materialized view (`player_xpts`). Pre-computed hourly from each player's last-5-GW xG/xA rates, FDR-based clean sheet probability, avg bonus, and saves. DGW players automatically get both fixtures summed. Returns full breakdown (goals/assists/CS/bonus/minutes) per player so advice is quantified, not qualitative. Used by Claude for transfer ranking, captain comparison, and start/bench decisions.

## [0.43.0] — 2026-04-28

### Fixed
- **Cache hit % over 100%** — was dividing cache_read_tokens by non-cached input_tokens only; denominator is now total tokens (input + cache_read + cache_write) so the percentage is always 0–100%.

## [0.42.0] — 2026-04-28

### Fixed
- **Fixture hallucination in transfer reasoning** — Claude was citing opponents from memory instead of tool results (e.g. stating the wrong fixture for a player). Now explicitly required to only mention a fixture if it came from a `get_team_all_fixtures` or `get_fixtures` call in the current conversation.
- **Defender double-up on same club** — transfer suggestions could recommend a DEF/GKP from the same club as one already in the squad. Now forbidden for mid/lower-table teams unless they have a DGW; Claude must flag the risk explicitly if the user insists.

## [0.41.0] — 2026-04-28

### Fixed
- **X-Ray removed entirely** — X-Ray SDK had no daemon running and was generating "No segment found" / "No segment to end" noise on every request. Removed all X-Ray imports and middleware calls; structured JSON logging to CloudWatch already covers all observability needs.
- **Redundant `search_team` calls before `get_team_all_fixtures`** — Claude was calling `search_team` to look up every team name before calling `get_team_all_fixtures`, doubling the tool calls on blank GW checks and chip queries. System prompt now explicitly forbids this — pass team names directly.
- **`get_player_recent_form` called one player at a time** — transfer queries were spending a full turn per candidate. Now instructed to batch all form checks into a single turn.
- **`get_gameweek_schedule` re-called despite pre-fetch** — system prompt rule reinforced: squad, chips, and schedule are pre-loaded; never call them again.

## [0.40.0] — 2026-04-28

### Fixed
- **X-Ray noise in logs** — removed `patch_all()` which was patching httpx and boto3 and flooding `/var/log/gaffer/app.log` with "No segment found" errors for every async HTTP call. Request-level X-Ray tracing via the middleware is preserved; per-call subsegments were not working in async context anyway.

## [0.39.0] — 2026-04-27

### Fixed
- **Free Hit squad in transfer advice** — when a Free Hit chip is active, `get_my_fpl_team` now also fetches the previous gameweek's picks and returns them as `original_squad`. Claude uses this to give transfer advice against the squad that will be restored after the Free Hit, not the temporary one.

## [0.38.0] — 2026-04-25

### Added
- **Admin dashboard** — password-protected `GET /admin/dashboard` endpoint queries CloudWatch Logs Insights and returns 9 metrics for the last 1h/24h/7d: total requests, errors + error rate, avg + p95 latency, input/output tokens, cache hit %, thumbs-down count, and missing photo count. React `/admin` page with time-range selector, live countdown, and auto-refresh every 60s. Password set via `ADMIN_PASSWORD` in Secrets Manager.

## [0.37.0] — 2026-04-25

### Fixed
- **Missing player photos** — some players (new signings, mid-season transfers) have no photo in the FPL bootstrap, producing a broken image URL. Previously the `<img>` was hidden on error, collapsing the chip layout. Now shows a fallback avatar (player's initial in a gold circle) so the chip always renders correctly.

## [0.36.0] — 2026-04-25

### Added
- **Thumbs-down feedback** — every assistant message now has a 👎 button. Clicking it opens a dialog pre-filled with the question that triggered the answer; user can describe what went wrong and submit. Sends an email via Resend (same pipeline as bug reports) and logs a `feedback.thumbsdown` event to CloudWatch.

## [0.35.0] — 2026-04-25

### Changed
- **Token usage logging** — every request now logs `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, and `tool_turns` to CloudWatch via the `claude.tokens` event. Previously there was no per-request cost visibility.
- **Tool-loop turn limit** — the Claude tool-use loop is now capped at 5 turns (`_MAX_TURNS`). If the model gets stuck calling tools repeatedly, the loop exits and a `claude.turn_limit_reached` warning is logged instead of making unbounded API calls.

## [0.34.0] — 2026-04-23

### Added
- **Captain suggester shortcut** — new `get_captain_options(player_names[])` tool fetches form, fixture difficulty, and ownership for all captain candidates in a single concurrent call. Previously Claude made 4–6 serial `get_player_recent_form` calls; now one call covers all candidates. System prompt updated to direct Claude to use this tool for captaincy questions.

## [0.33.0] — 2026-04-23

### Added
- **Mini-league standings** — new `get_mini_league_standings` tool fetches standings for any classic FPL league by ID. `get_my_fpl_team` now also returns `my_leagues` (the user's private leagues with IDs and current ranks) so Claude can look up standings without asking for an ID.

## [0.32.0] — 2026-04-23

### Changed
- **Database connection pooling** — `query_database` tool calls previously opened and closed a new asyncpg connection on every SQL query. Now uses a shared pool (min 2, max 10 connections) created at startup via FastAPI lifespan. Eliminates TCP handshake overhead on every tool call; `statement_timeout` set once at the pool level instead of per-query.

## [0.31.0] — 2026-04-23

### Fixed
- **Press ingest returning 0 RSS articles** — `_days_ago()` used `datetime.UTC` on the imported `datetime` class (not the module), which raises `AttributeError` at runtime; caught silently, returned 999 days, filtered every article as too old. Fixed to use `timezone.utc` instead.
- **Pinecone monthly token limit exhausted** — press ingest re-embedded all 301 player news vectors on every run even when nothing changed. `_upsert()` now fetches existing vector IDs from Pinecone first and only embeds documents whose IDs are not already present.

## [0.30.0] — 2026-04-23

### Fixed
- **Claude reporting teams as blank when they have a fixture** — the FPL API holds rearranged fixtures at `event=null` until officially confirmed, so they don't appear in the schedule fixture count and teams show as blank incorrectly. Fixed with two layers: (1) schedule now attaches a `blank_gw_warning` inline when blank teams are detected, requiring Claude to verify each one; (2) system prompt rule is now mandatory — Claude must call `get_team_all_fixtures` for every team in `blank_gameweek_teams` before reporting it as blank.

## [0.29.0] — 2026-04-23

### Fixed
- **Auto-merge fired despite failing UI build** — `gh pr merge --auto` only waits for required status checks; `ui-build`, `lint`, and `test` were not required so a failing build was ignored. `pr_review.py` now checks all non-claude-review check runs before calling auto-merge and skips it if any are already failing.
- **TypeScript build error in PlayerCard** — unused `fallback` prop caused `tsc -b` to fail with TS6133.

## [0.28.0] — 2026-04-22

### Fixed
- **Player cards were never shown** — `[[Player]]` tokens rendered as plain `<abbr>` elements (question-mark cursor, text-only tooltip). The `PlayerCard` component was completely disconnected from the rendering pipeline. Fixed: player names now render as inline chips with photo, team, position, price, form, points, and ownership.
- **Player card missing injury status, news, event points, ownership** — enriched backend response with `status`, `news`, `chance_of_playing_this_round`, `event_points`, `points_per_game`. Injury badge shows for injured/doubtful/suspended players; suppressed when chance is 100%.
- **Duplicate bootstrap cache** — `fpl_cache.py` maintained its own separate `/bootstrap-static/` cache independent of the tools layer. Consolidated to use the shared `_get_bootstrap()` cache, eliminating a redundant API call.
- **Unlabelled stat values on player card** — bare numbers like `5.0` and `45.8%` had no context. Stats now render as `Form 5.0 · 199 pts · 45.8% owned`.

## [0.27.0] — 2026-04-22

### Fixed
- **`get_gameweek_schedule` flagged false blank gameweeks for unscheduled GWs** — when a future gameweek had no fixtures assigned yet, all 20 teams were incorrectly flagged as blank. Now `blank_gameweek_teams` is only populated when the GW has at least one fixture assigned.
- **`get_gameweek_schedule` missing fixture difficulty** — fixtures were returned as plain `"ARS vs CHE"` strings with no difficulty rating. Each fixture now includes `home_difficulty` and `away_difficulty` (1–5 FPL scale) so Claude can assess fixture run quality directly from the pre-fetched schedule.

## [0.26.0] — 2026-04-21

### Fixed
- **`search_players_by_criteria` sorted by total points instead of form** — transfer recommendations were ranking season-long accumulators above in-form players. Results are now sorted by FPL form (descending) so Claude surfaces players on current hot streaks.
- **`search_players_by_criteria` missing defensive stats** — `clean_sheets`, `bonus`, and `saves` were absent from results. Defenders and keepers are now returned with full scoring context so Claude can make accurate position-specific transfer suggestions.

## [0.25.0] — 2026-04-21

### Fixed
- **Bootstrap cache bypassed in `get_my_fpl_team` and `get_chip_status`** — both functions were calling `/bootstrap-static/` directly on every request instead of using `_get_bootstrap()` which has a 1-hour TTL. Fixed to use the shared cache, saving 2 redundant API calls per request.
- **`get_player_stats` using API-Sports with no FPL data** — the tool was hitting API-Sports which returns raw football stats only, allowing Claude to fabricate FPL-specific values (points, bonus, CS). Migrated to PostgreSQL `players` table for accurate season aggregates. Removed the now-redundant `search_player` tool.

## [0.24.0] — 2026-04-21

### Fixed
- **`get_player_vs_opponent` using API-Sports with no FPL data** — same root cause as `get_player_recent_form` (v0.23.0): API-Sports `/fixtures/players` returns raw football stats only, forcing Claude to compute FPL points/CS/bonus itself and get them wrong. Rewrote the tool to query the PostgreSQL historical database directly, returning exact FPL figures (total_points, bonus, clean_sheets, xG, xA, minutes) per fixture. Player and opponent are now looked up by name via bootstrap — no API-Sports IDs needed.

## [0.23.0] — 2026-04-21

### Fixed
- **Wrong player form data (minutes, points, CS, bonus, opponents)** — `get_player_recent_form` was calling the API-Sports `/fixtures/players` endpoint which returns raw football stats only. Claude had to compute FPL points, clean sheets, and bonus itself and got them wrong. Rewrote the tool to call the FPL API's `/element-summary/{id}/` endpoint directly, which returns exact per-GW FPL figures (total_points, bonus, clean_sheets, minutes, goals_scored, assists, opponent_team). Player is now looked up by name via bootstrap data so no API-Sports player ID is needed.

## [0.22.0] — 2026-04-21

### Fixed
- **CD never fired after auto-merged PRs** — GitHub suppresses ALL workflow triggers (both `push` and `pull_request: closed`) when the merge is performed by `GITHUB_TOKEN` (anti-loop policy). `pr_review.py` was using `GITHUB_TOKEN` for `gh pr merge --auto`, so every auto-merged PR silently skipped CD. Fixed by passing `GH_PAT` (a Personal Access Token) as `GH_TOKEN` for the merge call — merges attributed to a real user trigger the `push: branches: [main]` event normally. Falls back to `GITHUB_TOKEN` if `GH_PAT` is not set. Added `workflow_dispatch` to `cd.yml` as a manual escape hatch.

### Setup required
- Add a fine-grained PAT with **Contents: Read and write** and **Pull requests: Read and write** on this repo as the `GH_PAT` secret in GitHub → Settings → Secrets → Actions.

## [0.21.0] — 2026-04-21

### Fixed
- **CD never fired after auto-merged PRs** — `cd.yml` triggered on `push: branches: [main]`, but GitHub suppresses push events caused by `GITHUB_TOKEN`-initiated merges (to prevent recursive loops). Since `pr_review.py` calls `gh pr merge --auto` with `GITHUB_TOKEN`, every auto-merged PR silently skipped CD. Fixed by switching the trigger to `pull_request: types: [closed]` — PR-close events are not suppressed by `GITHUB_TOKEN`. Also added `workflow_dispatch` as a manual escape hatch.

## [0.20.0] — 2026-04-21

### Fixed
- **ETL cron was silently failing** — `cronie` was never installed on EC2 so no scheduled jobs ran. Installed cronie + systemd-enabled crond. All four cron commands were also missing `ENVIRONMENT=production`, causing Secrets Manager to be skipped and `anthropic_api_key`/`api_sports_key` to be unset on every run. Added `ENVIRONMENT=production` to all cron entries in `setup_cron.sh`. Root cause of stale GW stats (e.g. Salah showing 0 minutes in GW31/32).
- **Auto-merge permission error** — `claude-pr-review.yml` had `contents: read`; `gh pr merge --auto` uses the GraphQL `mergePullRequest` mutation which requires `contents: write`. Changed to `write`.

### Changed
- **V1 removed** — `_build_system_prompt` V1 wrapper deleted; `version` field removed from `AskRequest`, `claude_client.ask()`, and `api.ts`. V2 (PostgreSQL + live tools + press RAG) is the only code path.
- **`fpl` Pinecone namespace removed** — `pipeline/ingest_fpl.py` and its tests deleted; daily `ingest_fpl` cron removed from `setup_cron.sh`. Pinecone now holds only the `press` namespace (injury news + match reports).
- **`get_v2_tool_definitions` renamed to `get_tool_definitions`** — no version suffix needed now that V1 is gone.

## [0.19.0] — 2026-04-20

### Fixed
- **Free-Hit/Wildcard squad composition** — system prompt now specifies the exact 15-player bench structure (2 GKP + 5 DEF + 5 MID + 3 FWD). Previously Claude could suggest 6 MID + 2 FWD because the rule only covered the starting XI minimum, not the total bench slots per position.
- **ETL dead-man's switch** — `run_snapshot` now emits a `Gaffer/ETL SnapshotSuccess` custom CloudWatch metric after every successful run. `setup_cloudwatch.sh` creates a CloudWatch alarm (`gaffer-etl-snapshot-missing`) that fires if no metric arrives in 2 consecutive hours, catching silent cron failures before users notice stale data.

### Changed
- **Shared httpx clients** — all FPL tool functions now share two persistent `httpx.AsyncClient` instances (one for API-Sports, one for the FPL API) instead of creating a new client per call. Eliminates repeated TCP handshakes on concurrent tool rounds, reducing per-request latency.

## [0.18.0] — 2026-04-20

### Changed
- **Simplified PR review** — replaced Important 🔴 / Nit 🟡 two-tier system with a single **Issues** list. A finding is only posted if it answers yes to: (1) is the change not doing what it's intended to do? or (2) will it break something in production causing a bad customer experience? Style concerns, theoretical correctness issues, and code that is ugly but correct are no longer flagged. `REVIEW.md` rewritten around these two questions. Commit status is now `failure` if any issues found, `success` otherwise.

## [0.17.0] — 2026-04-19

### Changed
- **6-hour TTL cache for `get_standings` and `get_gameweek_schedule`** — both are now served from an in-memory cache for 6 hours before hitting the external API again. GW schedule changes at most once per gameweek; standings update after match days. Cuts API-Sports calls on these two high-frequency tools to ~4/day regardless of request volume.

## [0.16.0] — 2026-04-19

### Fixed
- **CI auto-fix workflow** — `github_token` was missing from the `claude-code-action` call so Claude could authenticate but couldn't push commits. `git add`, `git commit`, and `git push` were also absent from `.claude/settings.local.json`, blocking Claude from writing fixes even if auth worked. Both gaps meant 3 attempts were consumed on every CI failure with no actual fix pushed.

## [0.15.0] — 2026-04-18

### Changed
- **Three-tier PR review** — replaced the single `claude-code-action` call with a custom Python script (`.github/scripts/pr_review.py`) that classifies each file via Haiku first: trivial files get a one-liner verdict only, minor files are fully reviewed by Haiku, significant files escalate to Sonnet. Prompt caching on the system prompt + REVIEW.md shared across all per-file calls. Non-reviewable files (lock files, generated, binary) are skipped before any API call. PRs touching only docs/comments across all files skip the review entirely. Token cap of ~4 000 tokens per file diff. Roll-up summary comment lists all files reviewed with collapsed section for trivial/skipped — nothing silently disappears.

## [0.14.0] — 2026-04-18

### Added
- **Review commit status** — PR review workflow now posts a `claude-review` commit status after Claude runs: `success` when clean or nit-only, `failure` when Important 🔴 findings exist. Requires branch protection with `claude-review` as a required status check to block merges on failing reviews.

## [0.13.0] — 2026-04-18

### Added
- **Rate limiting on `/fpl/ask`** — 10 requests/minute and 50/hour per IP using `slowapi`. Returns HTTP 429 when exceeded, protecting against accidental or intentional Anthropic API abuse.

## [0.12.0] — 2026-04-18

### Changed
- **Removed Docker and Kubernetes** — `docker/`, `docker-compose.yml`, and `k8s/` deleted; deployment is EC2 + systemd + nginx and these were never used in production
- **Removed unused dependencies** — `typer`, `rich`, and `mcp` removed from `requirements.txt`; CLI was removed in v0.8.0 and `mcp` was never imported
- **Fixed `CLAUDE.md`** — removed stale CLI/Click references; description updated to reflect web-app architecture

### Fixed
- **PR review workflow — inline comments now post correctly** (#84–#91) — resolved four sequential blockers: missing `github_token`, `--allowedTools` restriction blocking action-provided tools, `gh`/`git` commands blocked by `settings.local.json`, and prompt giving Claude no orientation on PR number or how to post comments

## [0.11.0] — 2026-04-17

### Added
- **Automated PR review** (`.github/workflows/claude-pr-review.yml`) — Claude reviews every PR on open/push, posts inline comments tagged Important 🔴 or Nit 🟡, caps nits at 5, and posts a summary verdict. Concurrency-controlled to cancel stale runs on the same PR.
- **CI auto-fix** (`.github/workflows/claude-ci-fix.yml`) — when CI fails on a PR branch, Claude fetches the logs, investigates the root cause, and pushes a minimal fix commit. Tracks attempts via `ci-fix-attempt-N` labels; stops after 3 failed attempts and flags for human review. Never auto-merges.
- **Interactive @claude** (`.github/workflows/claude-interactive.yml`) — responds to `@claude` mentions in PR comments and issue comments.
- **REVIEW.md** — defines review conventions, severity rules, FPL domain checks, and file skip patterns used by the review workflow.

## [0.10.0] — 2026-04-17

### Added
- **CLAUDE.md** — project context file loaded by Claude Code at the start of every session (stack, structure, conventions, FPL domain knowledge, deployment setup)
- **Pre-fetch architecture** — squad, chip status, and gameweek schedule are now fetched concurrently on the server before calling Claude, injected as a synthetic tool exchange to skip the first tool-use round; cuts transfer question latency by ~10–15 s
- **Prompt caching** — system prompt wrapped as a cacheable content block (`anthropic-beta: prompt-caching-2024-07-31`); cache reads count at 10% toward TPM, reducing 429 rate-limit errors
- **Null stripping** — `_strip_nulls()` removes `None` values from all tool results before sending to Claude, reducing token usage per round
- **FPL squad enrichment** — `get_my_fpl_team` now returns injury status, news, xG, xA, xGI, ICT index, ownership %, transfer delta, ITB, and squad value — previously these fields were ignored

### Fixed
- **Chip mid-season reset** — Triple Captain, Bench Boost, and Free Hit now correctly show as available after GW19 if used pre-reset; only post-GW19 uses count as spent
- **Position filter on transfer searches** — `search_players_by_criteria` is now always called with `position=` matching the outgoing player; wrong-position suggestions (e.g. FWD for a MID slot) are discarded before Claude sees them
- **Fixture source of truth** — when `get_gameweek_schedule` and `get_team_all_fixtures` disagree on GW number or opponent, `get_team_all_fixtures` is used as authoritative
- **Player search ambiguity** — `search_player` now includes `team` in results so Claude picks the correct player when multiple share a surname (e.g. Andersen)
- **X-Ray streaming error** — removed `xray_recorder.in_subsegment` calls from inside the SSE generator; the middleware ends the segment before the generator runs, causing "Already ended segment" errors
- **SSE timeout** — status events emitted before and between tool-use rounds keep the SSE connection alive through nginx's `proxy_read_timeout`; nginx timeout bumped to 300 s
- **FPL team ID in system prompt** — team ID is now threaded into the system prompt so Claude never asks the user for it mid-conversation
- **Start Fresh / Skip** — both now navigate to `?new=1`, creating a new chat session instead of reopening the existing one
- **Orphaned messages** — trailing empty assistant message and unpaired user message are cleaned up when loading sessions from localStorage
- **Transfer analysis accuracy** — tightened protocol: pre-loaded data used directly (no redundant tool calls), DNP vs 0-point distinction enforced, duplicate player names disallowed, chip availability sourced from pre-loaded data only

### Changed
- **Mobile landing nav** — replaced tag-cloud nav with scroll-only layout; nav hidden on mobile via CSS
- **Landing page polish** — amber theme, updated logo, global nav, chat mockups

## [0.8.0] — 2026-04-10

### Added
- **V2 mode** — opt-in via `?v=2` or the in-app toggle. Powered by PostgreSQL + text-to-SQL instead of the Pinecone vector search used in V1. Claude generates SQL queries against a structured database of historical FPL stats and executes them read-only with a safety blocklist and 5-second timeout.
- **PostgreSQL historical database** — 6-table schema (`seasons`, `teams`, `players`, `gameweeks`, `fixtures`, `gw_player_stats`) covering every Premier League gameweek going back multiple seasons. Indexed for common FPL query patterns (recent form, player-vs-opponent, cross-season comparisons).
- **ETL pipeline** (`pipeline/etl_v2.py`) — four run modes: `snapshot` (hourly live stats), `gw` (post-gameweek deep sync), `full` (both), and `backfill --season=YYYY` (historical data via API-Sports). Fully idempotent upserts so reruns are safe.
- **API-Sports historical backfill** — uses the API-Sports football API to fill past seasons (2022–2024) with per-fixture player stats that the FPL API doesn't expose.
- **Press & news RAG** (`pipeline/ingest_press.py`) — scrapes BBC Sport Premier League RSS and FPL player availability updates twice daily into a dedicated Pinecone `press` namespace. V2 responses are augmented with the 3 most relevant recent articles so Claude knows about injuries and manager quotes.
- **EC2 PostgreSQL setup** (`scripts/setup_postgres.sh`) — one-shot script that installs Postgres 16 on Amazon Linux 2023, creates `gaffer_etl` (read/write) and `gaffer_readonly` users with random passwords, applies the schema, and prints the connection strings ready for Secrets Manager.
- **Cron setup** (`scripts/setup_cron.sh`) — installs all scheduled jobs: hourly ETL snapshot, weekly post-GW sync, twice-daily press ingestion, and daily Pinecone refresh.
- **V2 banner in UI** — green toggle in the chat header to switch between V1 (RAG) and V2 (SQL + press RAG). Version is persisted in localStorage and survives refreshes.

### Changed
- **Pinecone repurposed** — V1's Pinecone namespace now holds genuine historical context (past-season aggregates and current-season player-vs-opponent breakdowns) instead of stale current-season snapshots. Current-season data is served live via tools.
- **Separate database credentials** — `DATABASE_ETL_URL` for the read/write pipeline, `DATABASE_URL` for the readonly app connection (principle of least privilege).
- **Model** — switched from `claude-opus-4-6` to `claude-sonnet-4-6` for faster responses.

### Removed
- **CLI** — removed; the app is exclusively web UI now.

## [0.7.0] — 2026-04-09

### Fixed
- **Returning users skip landing** — if an FPL team ID is already saved in localStorage, the landing page is bypassed and the user goes straight to the chat.
- **DGW/BGW detection reliability** — improved double and blank gameweek detection to handle rearranged fixtures with `event=null` in the FPL API.
- **Strict FPL transfer rules** — system prompt now enforces position constraints, form respect, budget checks, and squad structure rules when giving transfer advice.

### Changed
- FPL ID input is now surfaced more prominently on the landing page.

## [0.6.0] — 2026-04-09

### Fixed
- **Conversation history** — Claude now receives the full session history with every message, enabling genuine multi-turn conversations. Previously Claude had no memory of anything said earlier in the same chat.
- **Truncated responses** — increased `max_tokens` from 4096 to 8192; long answers no longer cut off mid-sentence.
- **Streaming hang** — tool calls now have a 20-second timeout; a slow or stalled API call returns a graceful error instead of hanging the stream indefinitely.
- **Missing tool status labels** — `search_players_by_criteria`, `get_chip_status`, and `get_gameweek_schedule` now show status text while running.
- **Player token rendering in tables** — `[[Name]]` tags inside markdown tables now resolve to tooltips correctly.

## [0.5.0] — 2026-04-09

### Added
- **Chip Advisor** — ask when to play your Bench Boost, Triple Captain, Free Hit, or Wildcard; The Gaffer checks which chips you have left and identifies upcoming double/blank gameweeks
- **Double & blank gameweek detection** — new `get_gameweek_schedule` tool flags DGW and BGW teams across the next 8 gameweeks
- **Player name tooltips** — hover any player name in a response to see their team, position, and price inline

### Changed
- Player search now covers all 825 FPL players (up from 400)
- Logo updated to 📋 the-gaffer.io

## [0.4.0] — 2026-04-07

### Added
- CloudWatch observability: structured JSON logs shipped to `/gaffer/production/api` log group
- HTTP request middleware logging method, path, status, and latency
- `ask.start`, `ask.complete`, `ask.error` log events with question, tools used, and latency
- EC2 User Data bootstrap script — new instances provision themselves automatically (no SSH required)
- SSM support via IAM policy for remote management

## [0.3.0] — 2026-04-06

### Added
- Live tool-use status in the chat bubble — shows what The Gaffer is doing while it thinks (e.g. "Fetching your FPL squad…", "Looking up player stats…") with a pulsing animation
- Feedback emails via Resend — bug reports now land reliably
- AWS Secrets Manager integration — all secrets fetched at startup in production
- Daily RAG re-ingestion via scheduled GitHub Actions (midnight UTC) to keep player data fresh

### Changed
- Removed SES dependency; replaced with Resend SDK
- CI: removed unused Docker build job

## [0.2.0] — 2026-04-05

### Added
- SSE streaming — Claude's answer appears word by word instead of all at once
- RAG pipeline — 1,129 FPL documents ingested into Pinecone (player stats, GW history, fixture difficulty, match results)
- EC2 hosting on `https://the-gaffer.io` with nginx + Let's Encrypt HTTPS
- GitHub Actions CD — auto-deploys to EC2 on merge to main
- Feedback form with bug reporting
- FPL team ID input with instructions
- Browser tab title and app branding

### Changed
- `nginx proxy_buffering off` to fix SSE streaming through reverse proxy
- `tool_choice: none` on final stream call to prevent Claude requesting more tools mid-answer

## [0.1.0] — 2026-04-05

### Added
- FastAPI server with `/fpl/ask` streaming endpoint and `/health` check
- Claude tool-use loop — parallel tool execution with `asyncio.gather`
- 12 FPL tools: squad, player stats, recent form, fixtures, standings, head-to-head, odds, and more
- React + TypeScript chat UI with session history persisted in localStorage
- RAG context injected into every Claude request via Pinecone vector search
- Pinecone ingestion pipeline for top 400 FPL players
- Terraform infrastructure: EC2 t3.small, Elastic IP, IAM role, ECR, security group
