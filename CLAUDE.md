# The Gaffer

AI-powered Fantasy Premier League analyst web app. Provides natural language analysis over FPL and World Cup 2026 data via a React chat UI backed by FastAPI and Claude tool-use.

## Stack
- **Language**: Python 3.11+
- **API**: FastAPI (rate-limited via `slowapi` — 10 req/min, 50 req/hour per IP on `/fpl/ask`)
- **AI**: Anthropic Claude via the `anthropic` SDK (text-to-SQL + RAG synthesis)
- **Database**: PostgreSQL (3 seasons of historical FPL stats)
- **RAG**: Pinecone (press conferences, injury updates)
- **Tracing**: AWS X-Ray
- **Infra**: AWS EC2, Terraform, GitHub Actions CI/CD

## Project structure
```
server/
  main.py              # FastAPI app — /fpl/ask is the main SSE endpoint
  claude_client.py     # Sport-agnostic Anthropic SDK wrapper; tool-use loop + streaming
  config.py            # All config via pydantic-settings `settings` object
  rag.py               # Pinecone RAG — queries the 'press' namespace only
  fpl_cache.py         # In-memory FPL bootstrap cache (player cards)
  logger.py            # Structured logging
  tools/
    fpl.py             # All 17 FPL tool implementations
    db.py              # query_database tool (text-to-SQL against PostgreSQL)
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
4. **Update the UI changelog** — bump the version string in `ui/src/Landing.tsx` ("What's new in vX.Y.Z →") and add a new entry at the top of `RELEASES` in `ui/src/ChangelogModal.tsx`

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
- **Current season**: 2025/26 — `_CURRENT_SEASON = "2025"` in `server/tools/fpl.py` (API-Sports uses start year)
- **Chip reset**: TC, Bench Boost, and Free Hit reset after GW19. Chips used in GW1–19 are available again in GW20–38. Only post-reset uses count as spent.
- **Wildcards**: two per season — GW1–19 and GW20–38 — separate API entries, no reset needed
- **FPL chip API names**: `3xc` (Triple Captain), `bboost` (Bench Boost), `freehit` (Free Hit), `wildcard`
- **Pre-fetch**: squad + chips + gameweek_schedule fetched concurrently before calling Claude, injected as a synthetic tool exchange to skip round-1 tool calls
- **Transfer rules**: position must be like-for-like (MID→MID only); always pass `position=` to `search_players_by_criteria` when finding replacements
- **Fixture source of truth**: `get_team_all_fixtures` wins over `get_gameweek_schedule` when they conflict
- **Player search**: `search_player` returns `team` so Claude can disambiguate players sharing a surname
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
- **ETL crons**: managed by `cronie` (must be installed via `sudo dnf install -y cronie && sudo systemctl enable --now crond`). All cron commands require `ENVIRONMENT=production` prefix — cron doesn't inherit the shell environment so Secrets Manager is skipped without it. Reinstall with `bash scripts/setup_cron.sh`. Three jobs: hourly snapshot, Tuesday GW sync, twice-daily press ingestion.
- **Press RAG sources**: BBC Sport PL RSS + The Guardian PL RSS (Sky Sports replaced — empty descriptions due to paywall). Player news from FPL bootstrap. Stale press articles (>14 days) deleted on each ingest run. Player news uses content-hash IDs so unchanged injury status is never re-embedded. Note: the `sports-context-mcp` package (separate repo) uses The Guardian content API instead of RSS — only the Gaffer's own `pipeline/` ETL uses RSS.
