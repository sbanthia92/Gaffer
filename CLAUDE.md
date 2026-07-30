# The Gaffer

AI-powered Fantasy Premier League analyst web app. Provides natural language analysis over FPL and World Cup 2026 data via a React chat UI backed by FastAPI and Claude tool-use.

## Stack
- **Language**: Python 3.11+
- **API**: FastAPI (rate-limited via `slowapi` — 10 req/min, 50 req/hour per IP on `/fpl/ask`)
- **AI**: Anthropic Claude via the `anthropic` SDK (tool-use loop + streaming)
- **Database**: PostgreSQL — current season GW-by-GW stats + past seasons aggregate totals (from FPL `history_past`). Per-fixture data only exists for the current season; historical data is season-level only.
- **MCP**: `sports-context-mcp` subprocess (stdio transport) — provides `query_historical_stats` and `query_press_conferences` tools to Claude
- **Infra**: AWS EC2, Terraform, GitHub Actions CI/CD

## Project structure
```
server/
  main.py              # FastAPI app — /fpl/ask is the main SSE endpoint; MCP session lifecycle
  claude_client.py     # Sport-agnostic Anthropic SDK wrapper; tool-use loop + streaming
  config.py            # All config via pydantic-settings `settings` object
  fpl_cache.py         # In-memory FPL bootstrap cache (player cards)
  logger.py            # Structured logging
  tools/
    fpl.py             # All 15 FPL tool implementations
    db.py              # Internal DB utility (asyncpg pool + execute); NOT a Claude tool
ui/                    # React + Vite + TypeScript frontend
tests/                 # pytest; asyncio_mode = auto
pipeline/              # ETL pipeline for PostgreSQL historical data
scripts/               # EC2 setup, deploy helpers
```

## External MCP package
`sports-context-mcp` is a standalone MCP server that exposes two tools (`query_press_conferences`, `query_historical_stats`) and two ingestion jobs (`ingest_press_content`, `ingest_match_data`). It lives in its own repo at `https://github.com/sbanthia92/sports-context-mcp` and is referenced as an external dependency in `requirements.txt`:
```
sports-context-mcp @ git+https://github.com/sbanthia92/sports-context-mcp.git
```
The press ingestion job in that package uses **The Guardian content API** (`content.guardianapis.com`) — not the Guardian RSS feed. The Gaffer's own `pipeline/` ETL still uses its own BBC Sport + Guardian RSS fetchers for the Pinecone press namespace.

## MCP client wiring
At startup, `server/main.py` finds the MCP `server.py` via `importlib.util.find_spec("config").origin` (the MCP's `config.py` in site-packages), launches it as a subprocess, and stores the `ClientSession` in `app.state.mcp_session`. Tool definitions are fetched at startup and merged with FPL tool definitions before being passed to Claude. When Claude calls `query_historical_stats` or `query_press_conferences`, `_v2_handler` routes through the MCP session. The DB connection pool (`db_tool`) is kept alive separately for FPL tools that use hard-coded SQL internally (`get_player_stats`, `get_player_vs_opponent`, `get_player_xpts`).

## Dev commands
```bash
# Lint + format (must pass before every commit)
ruff check . && ruff format .

# Tests
pytest tests/ -v

# Run server locally
uvicorn server.main:app --reload --port 8000
```

## Git workflow
- **Always branch from main**: `git checkout -b fix/description origin/main`
- **One branch = one PR** — never push to a merged branch
- **Never reuse a merged branch** — create a fresh one from `origin/main`
- **Before pushing**: `git pull --rebase origin main`; use `--force-with-lease` after a rebase
- **PR per fix** — if "and" appears in your commit message, split into two PRs
- **Delete branch after merge**: `git push origin --delete <branch>` once the PR is merged

## Every PR checklist
Every PR — no matter how small — must include all four of these:
1. **Bump the minor version** (`0.x.0 → 0.x+1.0`) in `CHANGELOG.md`
2. **Add a `CHANGELOG.md` entry** under the new version with what changed and why
3. **Update `CLAUDE.md`** if the change affects conventions, architecture, domain knowledge, or known gotchas
4. **Update the UI changelog** — add a new entry at the top of `RELEASES` in `ui/src/ChangelogModal.tsx`. `RELEASES` is exported and `Landing.tsx` reads `RELEASES[0].version` for the "What's new in vX.Y.Z →" button, so no separate version update in `Landing.tsx` is needed.

## Commit conventions (conventional commits)
- `feat:` — new user-facing behaviour
- `fix:` — bug fix
- `chore:` — formatting, CI, deps, tooling — no behaviour change
- `refactor:` — code restructure, no behaviour change
- `docs:` — documentation only

Be accurate — don't use `feat:` for a bug fix just because it involves new code.

## Code rules
- Line length: 100 chars (`ruff` enforces this)
- Config via `settings` only — never `os.environ` directly, never hardcode keys
- Mock all external calls in tests — never hit real APIs
- No speculative files or abstractions — only build what the current task needs

## API versioning
- **V2 is the only version** — V1 was removed; all requests use V2 (PostgreSQL + live tools + press RAG)
- Routes scoped by sport: `/fpl/ask`, not generic `/ask`

## FPL domain knowledge
- **Current season**: 2025/26 — derived from live FPL bootstrap data; no hardcoded season constant in `server/tools/fpl.py`
- **Chip reset**: TC, Bench Boost, and Free Hit reset after GW19. Chips used in GW1–19 are available again in GW20–38. Only post-reset uses count as spent.
- **Wildcards**: two per season — GW1–19 and GW20–38 — separate API entries, no reset needed
- **FPL chip API names**: `3xc` (Triple Captain), `bboost` (Bench Boost), `freehit` (Free Hit), `wildcard`
- **Pre-fetch**: squad + chips + gameweek_schedule fetched concurrently before calling Claude, injected as a synthetic tool exchange to skip round-1 tool calls
- **Transfer rules**: position must be like-for-like (MID→MID only); always pass `position=` to `search_players_by_criteria` when finding replacements
- **Fixture source of truth**: `get_team_all_fixtures` wins over `get_gameweek_schedule` when they conflict
- **Player search**: `search_players_by_criteria` returns `team` so Claude can disambiguate players sharing a surname
- **Squad composition**: A full FPL squad is exactly 15 players — 2 GKP, 5 DEF, 5 MID, 3 FWD. The starting XI must field at least 1 GKP, 3 DEF, 2 MID, 1 FWD. This is enforced in the system prompt so Free-Hit/Wildcard squads are always structurally valid.

## Streaming / X-Ray gotcha
The FastAPI middleware ends the X-Ray segment as soon as `StreamingResponse` is returned — **before** the async generator starts yielding SSE events. Never put `xray_recorder.in_subsegment()` calls inside `_generate()` — they throw "Already ended segment" errors.

## Agentic PR pipeline
Three Claude GitHub Actions workflows in `.github/workflows/`:
- **`claude-pr-review.yml`** — fires on PR open/push; runs `.github/scripts/pr_review.py` which classifies each file via Haiku (trivial/minor/significant), reviews minor files with Haiku and significant files with Sonnet, skips lock/binary/generated files and docs-only PRs, caps diffs at ~4 000 tokens, posts a single roll-up summary comment. A finding is only posted if it answers yes to: (1) is the change not doing what it's intended to do? or (2) will it break something in production causing a bad customer experience? Sets `claude-review` commit status (`success` when no issues, `failure` when issues found). Configure `claude-review` as a required status check in branch protection to block merges.
- **`claude-ci-fix.yml`** — fires when CI fails on a branch; investigates logs, pushes a minimal fix commit; tracks attempts via `ci-fix-attempt-N` labels; stops after 3 attempts
- **`claude-interactive.yml`** — fires on `@claude` mentions in PR/issue comments

Review conventions live in `REVIEW.md` at the repo root. Update it when conventions change.
Required secret: `ANTHROPIC_API_KEY` (set via GitHub repo settings → Secrets).

## Deployment
- **Production**: AWS EC2 (single instance), nginx reverse proxy (`proxy_read_timeout 300s`), systemd service
- **CI/CD**: GitHub Actions — CI on every PR targeting main, auto-deploy to EC2 on merge to main
- **Secrets**: AWS Secrets Manager (`gaffer/production`) — fetched at startup when `ENVIRONMENT=production`. No `.env` file on EC2.
- **SSH to EC2**: `ssh -i ~/.ssh/gaffer_ec2 ec2-user@the-gaffer.io`
- **ETL crons**: managed by `cronie` (must be installed via `sudo dnf install -y cronie && sudo systemctl enable --now crond`). All cron commands require `ENVIRONMENT=production` prefix — cron doesn't inherit the shell environment so Secrets Manager is skipped without it. Reinstall with `bash scripts/setup_cron.sh`. Four EC2 cron jobs: hourly snapshot, hourly `check_gw_complete` poll (fires `etl_v2 --mode=gw` only when a new gameweek finishes), twice-daily press ingestion (07:00 + 19:00 UTC), and a daily DB backup (02:15 UTC — see below). Press ingestion runs exclusively via EC2 cron — the `ingest.yml` GitHub Actions workflow was removed in v0.65.0 (it was broken and redundant). **Gotcha**: `setup_cron.sh`'s `add_job` matches by exact command string, so renaming/replacing a cron command (as happened when the old Tuesday-only GW cron was replaced by `check_gw_complete` in #159) does not remove the stale line — re-running the script only *adds* the new one. Always diff `crontab -l` against the script after a cron command changes and manually remove anything superseded. This drift was found in practice on 2026-07-30 — the live crontab was still running the old weekly GW cron months after #159 shipped the replacement.
- **DB backups**: `pipeline/backup_db.py` runs nightly (02:15 UTC), dumps via `DATABASE_URL` (read-only role — a backup never needs write access), gzips, uploads to S3 bucket `gaffer-db-backups-<account-id>` (terraform-managed, 30-day lifecycle expiration, no manual cleanup needed). This is the durability layer for EC2 instance replacement — EBS survives reboots, but a replaced instance gets a brand-new root volume, so this is the only thing that survives that.
- **Press RAG sources**: BBC Sport PL RSS + The Guardian content API (full article body) + FPL bootstrap player news. Stale press articles (>14 days) deleted on each ingest run. Player news uses content-hash IDs so unchanged injury status is never re-embedded. The ingestion job is `jobs.ingest_press_content` from the `sports-context-mcp` package — `pipeline/ingest_press.py` was removed when the MCP package became the canonical press ingest.
- **Job run metrics**: `pipeline/job_metrics.py` provides `record_attempt()` / `record_success()` / `record_failure()` helpers used by `run_press_ingest.py`, `check_gw_complete.py`, `backup_db.py`, and `etl_v2.py`'s snapshot mode. Each run writes to the `job_runs` table (Postgres). The `GET /admin/jobs` endpoint reads this table and adds Postgres row counts + Pinecone namespace stats. Migration applied on EC2 (2026-07-30): `db/migrations/001_job_runs.sql`.
- **ETL data integrity**: a 200 OK from the FPL API only proves the fetch succeeded, not that the write was correct. `etl_v2.py`'s hourly snapshot calls `_validate_snapshot()` after every upsert — compares player/team/fixture row counts against the source bootstrap payload, and spot-checks that the top scorer's `total_points` survived the write path unchanged. Raises (and records a `job_runs` failure) on any mismatch instead of silently completing with corrupted data.
- **DB role permissions gotcha**: the app-facing Postgres roles (`gaffer_readonly`, used via `DATABASE_URL`; `gaffer_etl`, used via `DATABASE_ETL_URL`) only have `USAGE` on the `public` schema, not `CREATE` — Postgres 15+ default. Any new table/view (migrations, `db/schema.sql` additions like `player_xpts`) must be applied as the `postgres` superuser, then explicitly `GRANT`ed to whichever role needs it (and `ALTER ... OWNER TO gaffer_etl` for anything a cron job needs to `REFRESH`/write). There's no stored superuser password — `pg_hba.conf` requires `md5` for every connection including local socket, so gaining superuser access means temporarily adding a `local all postgres trust` line, reloading Postgres, doing the change, then reverting and reloading again. **Sequences need their own grant**: table `SELECT` doesn't imply sequence `SELECT` — `pg_dump` (used by `backup_db.py`) reads every serial/identity column's backing sequence and fails with `permission denied for sequence ...` without it. Fixed on prod (2026-07-30) via `GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO gaffer_readonly` plus `ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT ON SEQUENCES TO gaffer_readonly` so future tables' sequences don't hit this again.
- **EC2 AMI is pinned** (`var.ec2_ami_id` in `terraform/variables.tf`), not resolved via a `most_recent = true` data source. That pattern re-resolves on every `terraform plan`/`apply` and will silently force-replace the running instance (new instance, new root EBS volume, production Postgres data gone) the moment AWS publishes a newer Amazon Linux 2023 AMI — this happened in practice on 2026-07-30. Only bump `ec2_ami_id` as a deliberate migration, with a DB backup/snapshot taken first. Always run `terraform plan` and check for `must be replaced` on `aws_instance.gaffer` before `apply`.
