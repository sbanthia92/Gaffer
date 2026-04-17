# The Gaffer — Claude Code Instructions

## What this project is
AI-powered Fantasy Premier League analyst at the-gaffer.io. Natural language Q&A about FPL ("Should I captain Salah?", "Help me make 3 transfers") powered by Claude with live FPL tools and conversation history.

- **V1**: Claude tool-use loop + 15 live FPL API tools (current default)
- **V2**: same + PostgreSQL text-to-SQL via `query_database` tool

## Key files
- `server/claude_client.py` — sport-agnostic Anthropic SDK wrapper; tool-use loop + SSE streaming
- `server/main.py` — FastAPI routes; `/fpl/ask` is the main endpoint
- `server/tools/fpl.py` — all FPL tool implementations (squad, chips, fixtures, odds, etc.)
- `server/config.py` — all config via `settings` (pydantic-settings); never `os.environ` directly
- `server/rag.py` — Pinecone RAG; always takes `namespace` + `recency_weight` params
- `ui/src/` — React frontend (Vite + TypeScript)
- `tests/` — pytest; `asyncio_mode = auto`

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
- **One branch per fix/feature** — never reuse a merged branch
- **Always `git pull --rebase origin main`** before pushing; use `--force-with-lease` if needed after rebase
- Each PR should contain one logical change; if "and" appears in the commit message, split it

## Commit conventions
- `feat:` — new user-facing behaviour
- `fix:` — bug fix
- `chore:` — formatting, deps, CI, no behaviour change
- `refactor:` — restructure, no behaviour change
- `docs:` — docs only

## Code rules
- Line length: 100 chars (`ruff` enforces)
- Python 3.11+, `asyncio_mode = auto` for tests
- Mock all external calls in tests — never hit real APIs
- Config via `settings` only — never hardcode keys or use `os.environ`
- No speculative files or abstractions — only build what's needed now

## FPL domain knowledge
- **Current season**: 2025/26 (`_CURRENT_SEASON = "2025"` in API-Sports)
- **Chip reset**: TC, Bench Boost, Free Hit reset after GW19 — chips used GW1–19 are available again in GW20–38
- **Wildcards**: two per season — one for GW1–19, one for GW20–38 (no reset, separate entries in chip history)
- **FPL chip API names**: `3xc` (Triple Captain), `bboost` (Bench Boost), `freehit` (Free Hit), `wildcard`
- **Pre-fetch on V2**: squad + chips + gameweek_schedule are fetched concurrently before calling Claude and injected as a synthetic tool exchange to skip round-1 tool calls
- **X-Ray**: middleware ends the segment before the SSE generator runs — no `xray_recorder.in_subsegment` calls inside `_generate()`

## Deployment
- **Currently**: AWS EC2 (single instance), nginx reverse proxy, systemd service
- **CI/CD**: GitHub Actions — CI on every push, CD auto-deploys to EC2 on merge to main
- **Nginx config**: `/etc/nginx/conf.d/gaffer.conf` on EC2; `proxy_read_timeout 300s`
- **Secrets**: `/etc/gaffer/.env` on EC2; never commit secrets
