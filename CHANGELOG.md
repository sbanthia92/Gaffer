# Changelog

All notable changes to The Gaffer are documented here.

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
