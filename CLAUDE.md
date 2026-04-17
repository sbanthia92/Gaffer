# The Gaffer

AI-powered sports analyst CLI. Provides natural language analysis over Fantasy Premier League and World Cup 2026 data.

## Stack
- **Language**: Python 3.11+
- **CLI**: Click (`gaffer` command entrypoint)
- **API**: FastAPI
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
  rag.py               # Pinecone RAG — always takes namespace + recency_weight params
  fpl_cache.py         # In-memory FPL bootstrap cache (player cards)
  logger.py            # Structured logging
  tools/
    fpl.py             # All 15 FPL tool implementations
    db.py              # V2 query_database tool (text-to-SQL)
ui/                    # React + Vite + TypeScript frontend
tests/                 # pytest; asyncio_mode = auto
pipeline/              # ETL pipeline for PostgreSQL historical data
scripts/               # EC2 setup, deploy helpers
```

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
Every PR — no matter how small — must include all three of these:
1. **Bump the minor version** (`0.x.0 → 0.x+1.0`) in `CHANGELOG.md`
2. **Add a `CHANGELOG.md` entry** under the new version with what changed and why
3. **Update `CLAUDE.md`** if the change affects conventions, architecture, domain knowledge, or known gotchas

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

## Streaming / X-Ray gotcha
The FastAPI middleware ends the X-Ray segment as soon as `StreamingResponse` is returned — **before** the async generator starts yielding SSE events. Never put `xray_recorder.in_subsegment()` calls inside `_generate()` — they throw "Already ended segment" errors.

## Agentic PR pipeline
Three Claude GitHub Actions workflows in `.github/workflows/`:
- **`claude-pr-review.yml`** — fires on PR open/push; posts inline Important 🔴 / Nit 🟡 comments; reads `REVIEW.md` for conventions; max 5 turns; concurrency-controlled per PR
- **`claude-ci-fix.yml`** — fires when CI fails on a branch; investigates logs, pushes a minimal fix commit; tracks attempts via `ci-fix-attempt-N` labels; stops after 3 attempts
- **`claude-interactive.yml`** — fires on `@claude` mentions in PR/issue comments

Review conventions live in `REVIEW.md` at the repo root. Update it when conventions change.
Required secret: `ANTHROPIC_API_KEY` (set via GitHub repo settings → Secrets).

## Deployment
- **Production**: AWS EC2 (single instance), nginx reverse proxy (`proxy_read_timeout 300s`), systemd service
- **CI/CD**: GitHub Actions — CI on every push, auto-deploy to EC2 on merge to main
- **Secrets**: `/etc/gaffer/.env` on EC2 — never commit secrets
- **SSH to EC2**: `ssh -i ~/.ssh/gaffer.pem ec2-user@<ELASTIC_IP>`
