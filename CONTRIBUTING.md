# Contributing

## Branching

```bash
git checkout -b feat/short-description
```

## Commits

Format: `type: short description`

| Type | When |
|------|------|
| `feat` | New feature |
| `fix` | Bug fix |
| `chore` | Config, tooling, infra — no production code |
| `test` | Adding or updating tests |
| `docs` | Documentation only |

Never bundle unrelated changes in one commit. If you find yourself writing "and" in a commit message, split it.

## Before every commit

```bash
ruff check . && ruff format .
pytest tests/ -v
```

Both must pass clean before committing.

## Pull Requests

- One feature per PR
- CI must be green before merging
- Update `CHANGELOG.md` under `[Unreleased]` with what changed

## Environment

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

## Local dev

```bash
docker compose up
```

The API will be available at `http://localhost:8000`.
