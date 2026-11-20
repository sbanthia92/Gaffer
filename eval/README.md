# The Gaffer eval

An answer-quality eval for The Gaffer: a fixed set of realistic questions, run through
the real app, graded in code, scored. The unit tests in `tests/` mock the model, so
they show the plumbing works but not whether the answers are any good. This shows that.

This is version 1: run by hand, no CI gate yet (see *Next steps*).

## Run it

```bash
# A throwaway Postgres (any will do; the database is dropped and rebuilt every run)
docker run -d --name gaffer-eval-db -p 5433:5432 -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16

# ANTHROPIC_API_KEY must be set (env or .env) — this makes real model calls
python -m eval.run --database-url postgresql://postgres@localhost:5433/postgres
```

Useful flags: `--only id1,id2` (a few questions), `--tier must_pass`, `--holdout`
(also run the hold-out set), `--repeats 3` (measure noise), `--compare <results.json>`
(what got better or worse since an earlier run), `--no-build` (reuse the database).

Each run writes `eval/results/<timestamp>/results.json` (every answer, tool call, check
result, token count) and `summary.md`. Read the answers, not just the score.

**When to run it:** after changing anything that can change an answer — the system
prompt or `_MODEL` (`server/claude_client.py`), tools (`server/tools/`), pre-fetch or
tool wiring (`server/main.py`), the `fpl-context-mcp` or `anthropic` version, the DB
schema, or the ETL. Not for UI, infra or docs changes.

**Cost:** each question is a full agent run (3–4 model calls of 15–25k input tokens
each), roughly $0.15–0.35 on Sonnet 4.6 — about $5–12 for the 33 questions, plus
cents for the extraction model. The summary reports the real figure.

## How it works

```
questions.yaml ──► run.py ──► the real FastAPI app, in-process (harness.py)
                               │  /fpl/ask → pre-fetch → Claude tool loop → tools
                               │
              frozen world ────┤  FPL API      → snapshot replay      (replay.py)
              (same every run) │  SQL tools    → DB rebuilt from it   (build_db.py)
                               │  managers     → synthetic squads     (managers.py)
                               │  today's date → recording date
                               │  web search   → fixed "no news" stub
                               ▼
                      transcript ──► checks.py (+ keys.py) ──► results.json, summary.md
```

Nothing in `server/` is modified; the eval patches module attributes for the run.

### Why freeze the data

A score means something only if it moves because the code changed, not because
Haaland scored on Saturday. So the FPL API is recorded once (`eval/snapshots/`) and
replayed:

- **FPL API:** `record.py` saves the bootstrap, fixtures and every player's summary
  (~770 KB gzipped). Requests it can't answer return 404 and are listed per question.
- **Database:** `build_db.py` runs the production ETL (`pipeline/etl_v2`) with its
  fetches answered from the snapshot, so the SQL tools and the live tools see the same
  world. Last season's clubs can't come from the API, so they're a small file.
- **Managers:** squads, chips and a mini-league are synthetic (`managers.py`), built by
  fixed rules from the snapshot. No real manager's data is stored. Some are deliberate
  traps, e.g. a squad that already has 3 players from the club of the obvious transfer.
- **Web search** runs on Anthropic's side and its results change daily, so it can't be
  replayed. It becomes a client-side tool with the same name that always returns
  nothing, which makes the model fall back on FPL's own injury fields.
- **Sampling:** the eval would use temperature 0, but the current SDK (`anthropic`
  2.x, API version `2026-10-21`) no longer accepts `temperature`. Answers vary run to
  run, which is why noise has to be measured (`--repeats`) before thresholds are set.

Re-record deliberately, between gameweeks (e.g. start of a season):
`python -m eval.record --name 2026-27-gw20`, then point `DEFAULT_SNAPSHOT` at it in
its own PR. Scores from different snapshots are not comparable.

### How the questions were chosen

`questions.yaml` holds 33 questions (+3 in `questions_holdout.yaml`):

- **Known failures first** — every answer-affecting bug in `CHANGELOG.md` became a
  question: stale "promoted" clubs, a 4th player from one club, fixtures from memory,
  no FDR 5 warning, xPts dropping squad players, answers ending in "let me fetch…",
  illegal Free Hit squads, chips misreported, invented past-season xG, 0 points read as
  "didn't play". The old `scripts/eval_stale_knowledge.py` checks are folded in here.
- **Edge cases** — unknown player, ambiguous surname, invalid team ID, off-topic.
- **Typical questions** — captaincy, transfers, chips, fixtures, player stats, league
  table, mini-league, price changes. Hand-written for now; they should be re-weighted
  towards what users actually ask once question logs are mined.

Two tiers: **must_pass** (past bugs, rule breaks, traps, edge cases — any failure
matters) and **scored** (typical questions — tracked as a percentage). The **hold-out**
questions are never used to tune prompts; the summary shows only their total, so
tuning can't leak into them.

The question text is fixed, but names and expected answers are filled in from the
snapshot (`vars`, `keys.py`), e.g. "Should I bring in {player}?" where `player` is
whoever faces an FDR 5 fixture next. The set grows: every bad answer a user reports
becomes a question. A question is never edited to make it pass.

### How answers are graded

All in code, against the frozen data — answer keys are computed, never hand-typed:

| Check | What it verifies |
|---|---|
| `mentions` / `not_mentions` | names, opponents, positions computed from the snapshot appear (accent- and case-insensitive) |
| `tools` | the right tools were called, with the right arguments (e.g. `position=MID`) |
| `transfer_rules` | recommended transfers: same position, ≤3 per club, within budget, not already owned |
| `squad_rules` | a proposed squad: 15 players, 2/5/5/3, ≤3 per club, ≤£100m |
| `promotion` | no club called promoted unless this season's data says so |
| `chips`, `first_player`, `ends_cleanly`, `regex_any/none` | targeted regressions |
| always: `no_error`, `loop` | an answer came back; no tool-turn cap hit, no identical repeat calls, no re-fetching pre-loaded data |
| always: `grounding` | report-only: numbers in the answer that no tool result contains |

`transfer_rules` and `squad_rules` first ask a small model (Haiku 5.5) to *extract*
which players the answer recommends, because free text can't be parsed reliably; the
rules themselves are checked in code. There is no LLM judge of advice quality yet.

### Why ~33 questions, and what a score can tell you

With n questions and a true pass rate p, one run's score has a 95% margin of error of
about ±1.96·√(p(1−p)/n):

| scored questions | margin at p = 0.8 |
|---|---|
| 15 | ±20 points |
| 30 | ±14 points |
| 100 | ±8 points |

So a single run of this set only reliably shows a large drop. That's fine for version
1: its job is to cover each kind of question a few times and catch obvious breaks.
Two things make it more sensitive than the margin suggests: must_pass questions are
pass/fail one by one (one regression is visible), and comparing runs question by
question (`--compare`) shows exactly what flipped. A precise overall score would need
~100 questions and costs grow linearly.

## Adding a question

Add an entry to `questions.yaml` (format at the top of the file). Prefer checks that
compute the expected answer from the snapshot (`{key: ...}` → `keys.py`). Then:

```bash
pytest tests/test_eval.py                                      # it resolves
python -m eval.run --database-url ... --only <new-id>          # it behaves
```

## Known gaps

- **Web search is stubbed,** so news-driven answers aren't tested.
- **No blank/double gameweek** in this snapshot (no `event=null` fixtures), so the
  blank-gameweek regression isn't covered yet; it needs a scenario overlay on top of
  the snapshot.
- **No manager-change trap:** no tool returns club managers, so there's no key to check
  against.
- **Last season's clubs are hand-entered** (`previous_season_teams.json`); verify
  against the production `teams` table when re-recording.
- **`league-mini-league-implicit` is expected to fail:** real FPL marks private leagues
  `league_type: "x"`, but `get_my_fpl_team` keeps only `"c"`, so `my_leagues` is always
  empty and the model can't find the user's league.
- The old stale-knowledge script could hit production by URL; this eval runs only
  against the frozen snapshot.

## Next steps

1. Run the suite 5 times on main (`--repeats 5`) to measure noise; set thresholds just
   above it.
2. Gate CI on it, only for PRs that touch the answer-affecting paths above.
3. Mine real questions (read-only, anonymised) to re-weight the scored tier.
4. Record real web-search results; add an LLM judge for advice quality (report-only).
