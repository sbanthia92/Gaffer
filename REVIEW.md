# Code Review Conventions — The Gaffer

This file is read by the automated PR review workflow. It defines what to flag and how.

## Severity levels
- **Important 🔴** — must be fixed before merge: correctness bugs, security issues, broken conventions, data integrity risks
- **Nit 🟡** — style, naming, minor clarity issues — nice to fix but not blocking

---

## Python conventions

### Always flag as Important 🔴
- `os.environ` used directly in `server/` code — must use `settings` from `server/config.py` (standalone scripts in `.github/scripts/` are exempt)
- Hardcoded API keys, secrets, or credentials anywhere in code
- `except:` or `except Exception:` with no re-raise or structured error return — swallowed exceptions hide bugs
- Tool handler functions that hit real external APIs in tests — all external calls must be mocked
- `xray_recorder.in_subsegment()` inside `_generate()` or any async SSE generator — the middleware ends the segment before the generator runs (see CLAUDE.md)
- `betas=` kwarg on Anthropic SDK calls — use `extra_headers={"anthropic-beta": "..."}` instead
- Missing `position=` param when calling `search_players_by_criteria` for transfer suggestions
- Cross-position transfer recommendations (MID replaced by FWD/DEF/GKP etc.)
- Committing to a merged branch instead of branching from `origin/main`

### Flag as Nit 🟡
- Missing type hints on public functions (functions without leading `_`)
- Line length over 100 chars (ruff enforces this — flag only if ruff wouldn't catch it, e.g. comments)
- Multi-line docstrings on internal helpers — one short line max
- Comments that describe *what* the code does rather than *why*
- `print()` statements left in `server/` code — use `log` from `server/logger.py` (stdout is the correct log sink in `.github/scripts/`)
- Unused imports

---

## Commit and PR conventions

### Flag as Important 🔴
- PR contains unrelated changes that should be separate PRs ("and" in the commit message often signals this)
- No `CHANGELOG.md` update — every PR must bump the minor version and add an entry
- Incorrect commit prefix: `feat:` used for a bug fix, `fix:` used for new behaviour

### Flag as Nit 🟡
- Commit message describes *what* changed rather than *why*
- Branch not deleted after merge (can't be checked in review, but flag in summary if branch name suggests a reused branch)

---

## FPL domain correctness

### Flag as Important 🔴
- Chip availability logic that doesn't account for the GW19 mid-season reset (TC, BB, FH reset after GW19)
- `get_gameweek_schedule` used as the sole source for DGW/BGW conclusions without `get_team_all_fixtures` verification
- `get_my_fpl_team` or `get_chip_status` called inside the tool-use loop when pre-fetched data is available
- Transfer advice that ignores the `itb` field (in-the-bank) from squad data
- Season constant `_CURRENT_SEASON` changed without updating CLAUDE.md

### Flag as Nit 🟡
- Tool label missing from `_TOOL_LABELS` in `claude_client.py` for a newly added tool

---

## Files to skip entirely
- `tests/fixtures/` — test data, not production code
- `**/package-lock.json`, `**/*.lock` — lockfiles
- `db/migrations/` — migration files
- `terraform/`, `k8s/`, `infra/` — infrastructure definitions
- `pipeline/` — ETL pipeline (separate concern, reviewed separately)
- `.github/scripts/` — CI/CD helper scripts (infrastructure, not application code)

---

## Comment format
Post findings as inline comments at the relevant file + line. Each comment must include:
- Severity tag: **Important 🔴** or **Nit 🟡**
- One sentence describing the issue
- One sentence explaining why it matters or what rule it violates
- A suggested fix if one is obvious

End with a summary comment on the PR listing: total Important findings, total Nit findings, and if nits were capped, the count of remaining uncapped nits.
