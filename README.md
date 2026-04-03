# The Gaffer

An AI-powered football analyst CLI. Ask natural language questions about Fantasy Premier League and get answers grounded in live data and historical context.

```bash
gaffer ask "Should I captain Salah this week?" --league fpl
gaffer ask "Who should I transfer in for the next 5 gameweeks?" --league fpl
gaffer fixtures --league fpl
gaffer standings --league fpl
gaffer odds --match "Liverpool vs Man City" --league fpl
gaffer health
```

## How it works

Every answer draws from three layers:

1. **Live data (MCP tools)** — last 10 games, fixture difficulty, current odds via API-Sports
2. **Player-level RAG (Pinecone)** — historical h2h records, home/away splits, seasonal form
3. **Team-level RAG (Pinecone)** — defensive records, head-to-head patterns across seasons

Claude receives all three layers and generates the answer. This is what makes The Gaffer better than asking Claude directly — the base model doesn't know recent form, live odds, or historical h2h records.

## Phases

| Phase | Competition | Status |
|-------|-------------|--------|
| 1 | Fantasy Premier League | In progress |
| 2 | FIFA World Cup 2026 | From June 11 2026 |

## Stack

- **Backend:** Python 3.11, FastAPI, Anthropic SDK, MCP
- **RAG:** Pinecone (built-in inference)
- **CLI:** Typer + Rich
- **Infra:** Docker, GitHub Actions, AWS EKS, Terraform

## Setup

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY, PINECONE_API_KEY, API_SPORTS_KEY

docker compose up
```

API available at `http://localhost:8000`. Health check: `GET /health`.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check . && ruff format .
pytest tests/ -v
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `PINECONE_API_KEY` | Yes | Pinecone API key |
| `PINECONE_INDEX_NAME` | No | Defaults to `the-gaffer` |
| `API_SPORTS_KEY` | Yes | api-sports.io key |
| `SERVER_PORT` | No | Defaults to `8000` |
| `ENVIRONMENT` | No | Defaults to `development` |
