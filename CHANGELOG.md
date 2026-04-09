# Changelog

All notable changes to The Gaffer are documented here.

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
