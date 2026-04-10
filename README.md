# The Gaffer

An AI-powered FPL analyst. Ask anything about your Fantasy Premier League squad and get a clear verdict backed by live data, stats, and historical context.

**Live at [the-gaffer.io](https://the-gaffer.io)**

## What it does

Every answer draws from three layers:

1. **Live data (tools)** — current squad, player stats, fixture difficulty, standings, odds via API-Sports + FPL API
2. **Historical RAG (Pinecone)** — h2h records, seasonal form, gameweek history for all 825 FPL players
3. **Claude** — synthesises both into a structured VERDICT → DATA → REASONING response, with full conversation history so follow-up questions work naturally

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, Anthropic SDK |
| AI | Claude claude-opus-4-6, multi-turn tool-use loop, SSE streaming |
| RAG | Pinecone (multilingual-e5-large embeddings) |
| Frontend | React + TypeScript + Vite |
| Infra | EC2 t3.small, nginx, Let's Encrypt, Terraform |
| CI/CD | GitHub Actions — lint, test, deploy on merge to main |
| Secrets | AWS Secrets Manager |
| Observability | CloudWatch structured JSON logs |

## Local development

```bash
# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .

# Copy and fill in secrets
cp .env.example .env

# Run the API
uvicorn server.main:app --reload

# Run the UI
cd ui && npm install && npm run dev
```

API at `http://localhost:8000`. UI at `http://localhost:5173`.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `PINECONE_API_KEY` | Yes | Pinecone API key |
| `PINECONE_INDEX_NAME` | No | Defaults to `the-gaffer` |
| `API_SPORTS_KEY` | Yes | api-sports.io key |
| `RESEND_API_KEY` | Yes | Resend API key (feedback emails) |
| `FEEDBACK_EMAIL` | Yes | Email to receive bug reports |
| `ENVIRONMENT` | No | `development` (local) or `production` (EC2) |
| `SERVER_PORT` | No | Defaults to `8000` |

In production, all secrets are fetched from AWS Secrets Manager (`gaffer/production`) at startup.

## RAG ingestion

```bash
python -m pipeline.ingest_fpl
```

Ingests historical FPL data for all 825 players into Pinecone. Also runs nightly via GitHub Actions at midnight UTC.

**What's stored:**
- `player_season_history` — past season aggregates (goals, assists, points, price) from the FPL API `history_past` endpoint
- `player_vs_opponent` — current season GW-by-GW records grouped by opponent, so Claude can answer "how has Salah performed vs Arsenal this season?"

**Known limitation:** Player-vs-opponent breakdowns only cover the **current season**. The FPL API's `history_past` endpoint returns season totals only — it does not expose per-fixture data for past seasons. Historical player-vs-opponent context (e.g. 2024/25, 2023/24) would require an external dataset such as [vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League).

## Lint & test

```bash
ruff check . && ruff format .
pytest tests/ -v
```

## Deployment

Merging to `main` triggers the CD workflow which:
1. Builds the React UI
2. SSH deploys to EC2 (git pull, pip install, npm build, systemctl restart)

Infrastructure managed with Terraform in `terraform/`.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
