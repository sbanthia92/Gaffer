# Changelog

All notable changes to The Gaffer are documented here.

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
