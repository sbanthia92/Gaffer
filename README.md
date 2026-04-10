# The Gaffer

An AI-powered FPL analyst. Ask anything about your Fantasy Premier League squad and get a clear verdict backed by live data, historical stats, and the latest news.

**Live at [the-gaffer.io](https://the-gaffer.io)**

---

## What it does

Every answer draws from three layers:

1. **Live data (tools)** — current squad, player stats, fixture difficulty, standings, and odds via the FPL API and API-Sports
2. **Historical database (V2)** — PostgreSQL storing multiple seasons of per-gameweek player stats; Claude writes SQL queries against it to answer questions like "how has Salah performed against Arsenal over the last two seasons?"
3. **News & press RAG** — BBC Sport match reports and FPL injury updates ingested into Pinecone twice daily so Claude knows about last night's press conference

Responses always follow a **VERDICT → DATA → REASONING** structure with full conversation history so follow-up questions work naturally.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, SSE streaming |
| AI | Claude claude-sonnet-4-6, multi-turn tool-use loop |
| Text-to-SQL | Claude generates SQL → read-only PostgreSQL (asyncpg) |
| Historical RAG | Pinecone (multilingual-e5-large) — press/news namespace |
| Frontend | React + TypeScript + Vite |
| ETL | Custom pipeline (snapshot / GW / backfill modes), API-Sports |
| Infra | EC2 t3.small, PostgreSQL 16, nginx, Let's Encrypt |
| CI/CD | GitHub Actions — lint, test, deploy, nightly RAG ingest |
| Secrets | AWS Secrets Manager |
| Observability | AWS X-Ray tracing, CloudWatch structured JSON logs |

---

## Architecture (V2)

```
User question
     │
     ▼
FastAPI /fpl/ask
     │
     ├── rag.retrieve(namespace="press")   ← recent news/injuries from Pinecone
     │
     └── claude_client.ask(version=2)
              │
              ├── query_database → Claude writes SQL → asyncpg (read-only)
              ├── get_my_fpl_team / get_chip_status → FPL API
              ├── get_fixtures / get_odds → API-Sports
              └── search_players_by_criteria → FPL API
```

V1 (the original) is still available and uses Pinecone vector search over historical season aggregates instead of the SQL database.

---

## Local development

```bash
# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .

# Copy and fill in secrets
cp .env.example .env

# Run the API
uvicorn server.main:app --reload

# Run the UI (separate terminal)
cd ui && npm install && npm run dev
```

API at `http://localhost:8000`. UI at `http://localhost:5173`.

Use `?v=2` to enable V2 mode locally (requires a running PostgreSQL instance).

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `PINECONE_API_KEY` | Yes | Pinecone API key |
| `PINECONE_INDEX_NAME` | No | Defaults to `the-gaffer` |
| `API_SPORTS_KEY` | Yes | api-sports.io key |
| `RESEND_API_KEY` | Yes | Resend API key (feedback emails) |
| `FEEDBACK_EMAIL` | Yes | Email to receive bug reports |
| `DATABASE_URL` | V2 only | `postgresql://gaffer_readonly:...@localhost:5432/gaffer` |
| `DATABASE_ETL_URL` | V2 only | `postgresql://gaffer_etl:...@localhost:5432/gaffer` |
| `ENVIRONMENT` | No | `development` (local) or `production` (EC2) |
| `SERVER_PORT` | No | Defaults to `8000` |

In production, all secrets are fetched from AWS Secrets Manager (`gaffer/production`) at startup.

---

## ETL & ingestion

### Historical backfill (one-time)
```bash
# Run one season per day to stay within API-Sports rate limits
python -m pipeline.etl_v2 --mode=backfill --season=2024
python -m pipeline.etl_v2 --mode=backfill --season=2023
python -m pipeline.etl_v2 --mode=backfill --season=2022
```

### Scheduled (managed by EC2 cron — see `scripts/setup_cron.sh`)
```bash
python -m pipeline.etl_v2 --mode=snapshot  # hourly — live stat refresh
python -m pipeline.etl_v2 --mode=gw        # weekly — post-gameweek deep sync
python -m pipeline.ingest_press            # twice daily — news & injuries → Pinecone
python -m pipeline.ingest_fpl             # daily — historical player data → Pinecone
```

---

## EC2 setup (first time)

```bash
bash scripts/setup_postgres.sh   # install Postgres, create users, apply schema
# → copy printed DATABASE_URL values into AWS Secrets Manager

python -m pipeline.etl_v2 --mode=full   # seed current season

bash scripts/setup_cron.sh              # install scheduled jobs
```

---

## Lint & test

```bash
ruff check . && ruff format .
pytest tests/ -v
```

---

## Deployment

Merging to `main` triggers the CD workflow which:
1. Builds the React UI
2. SSH deploys to EC2 (git pull, pip install, npm build, systemctl restart)

Infrastructure managed with Terraform in `terraform/`.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
