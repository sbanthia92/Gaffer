# Code Review Conventions — The Gaffer

This file is read by the automated PR review workflow.

## The only two questions that matter

For every finding, the reviewer must answer **yes** to at least one of these before flagging it:

1. **Is the change not doing what it's intended to do?** (incorrect logic, wrong data, broken behaviour)
2. **Will it break something else in production, causing a bad customer experience?** (regression, data loss, outage, security hole, wrong FPL advice)

If the answer to both is "no" — even if the code is ugly, theoretical, or style-inconsistent — do not flag it.

---

## Things that always answer "yes" to one of the above

### Python / server

- `os.environ` used directly in `server/` — must use `settings` from `server/config.py`; breaks if env isn't set at startup
- Hardcoded API keys or secrets anywhere in code
- `except:` or `except Exception:` with no re-raise or structured error return — swallowed exceptions hide real failures from users
- External API calls in tests that aren't mocked — makes CI depend on live services
- `xray_recorder.in_subsegment()` inside `_generate()` or any async SSE generator — throws "Already ended segment" at runtime
- `betas=` kwarg on Anthropic SDK calls — use `extra_headers={"anthropic-beta": "..."}` instead; `betas=` silently fails
- Missing `position=` param when calling `search_players_by_criteria` for transfer suggestions — causes wrong-position recommendations to reach users

### FPL domain correctness

- Chip availability logic that ignores the GW19 mid-season reset (TC, BB, FH reset after GW19) — gives users wrong chip advice
- `get_gameweek_schedule` used as sole source for DGW/BGW without `get_team_all_fixtures` verification — produces incorrect fixture data
- `get_my_fpl_team` or `get_chip_status` called inside the tool-use loop when pre-fetched data is available — doubles latency for users
- Transfer advice that ignores `itb` (in-the-bank) from squad data — recommends transfers the user can't afford

### PR / commit conventions

- No `CHANGELOG.md` update — every PR must bump the minor version and add an entry (required process, blocks tracking)
- Committing to a merged branch instead of branching from `origin/main` — corrupts git history

---

## Files to skip entirely

- `tests/fixtures/` — test data
- `**/package-lock.json`, `**/*.lock` — lockfiles
- `db/migrations/` — migration files
- `terraform/`, `k8s/`, `infra/` — infrastructure definitions
- `pipeline/` — ETL pipeline
- `.github/scripts/` — CI/CD helper scripts

---

## Comment format

Post a single roll-up comment with an **Issues** section listing each problem:

- `filename:line` — what's wrong and why it will break something for users or makes the change incorrect

If there are no issues, say so clearly. Do not flag theoretical concerns, style preferences, or improvements that don't answer "yes" to the two questions above.
