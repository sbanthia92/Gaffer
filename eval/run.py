"""
Run the eval by hand:

    python -m eval.run --database-url postgresql://postgres@localhost:5432/gaffer_eval
    python -m eval.run ... --only cap-who,reg-three-per-club     # a few questions
    python -m eval.run ... --compare eval/results/<earlier>/results.json
    python -m eval.run ... --repeats 3                           # measure noise

Needs ANTHROPIC_API_KEY (real model calls — see eval/README.md for cost) and a
throwaway Postgres database, which is rebuilt from the snapshot unless --no-build.
Writes eval/results/<timestamp>/results.json and summary.md.
"""

import argparse
import asyncio
import inspect
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

import yaml

from eval import build_db
from eval import checks as C
from eval import managers as M
from eval.harness import Harness, Transcript
from eval.keys import KEYS, World
from eval.snapshot import DEFAULT_SNAPSHOT, Snapshot

EVAL_DIR = Path(__file__).parent
QUESTIONS = EVAL_DIR / "questions.yaml"
HOLDOUT = EVAL_DIR / "questions_holdout.yaml"
RESULTS_DIR = EVAL_DIR / "results"

# $ per million tokens. cache_write is the 5-minute TTL rate.
PRICES = {
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    C.EXTRACTOR_MODEL: {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
}
_MANAGERS = {
    "BALANCED": M.BALANCED,
    "THREE_CLUB": M.THREE_CLUB,
    "CHIPS_USED": M.CHIPS_USED,
    "FREE_HIT": M.FREE_HIT,
    "INVALID": M.INVALID,
}


# ── Questions ─────────────────────────────────────────────────────────────────


def resolve(value, world: World, variables: dict):
    """Turn {key: ...} / {var: ...} / manager names in a question into concrete values."""
    if isinstance(value, dict):
        if "key" in value and set(value) <= {"key", "args"}:
            args = resolve(value.get("args", {}), world, variables)
            return KEYS[value["key"]](world, **args)
        if set(value) == {"var"}:
            return variables[value["var"]]
        return {k: resolve(v, world, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, world, variables) for v in value]
    if isinstance(value, str) and value in _MANAGERS:
        return _MANAGERS[value]
    return value


def load_questions(world: World, holdout: bool = False) -> list[dict]:
    raw = yaml.safe_load(QUESTIONS.read_text())
    if holdout:
        raw += [{**q, "holdout": True} for q in yaml.safe_load(HOLDOUT.read_text())]
    ids = [q["id"] for q in raw]
    assert len(ids) == len(set(ids)), "duplicate question ids"
    questions = []
    for q in raw:
        variables = {k: resolve(v, world, {}) for k, v in (q.get("vars") or {}).items()}
        questions.append(
            {
                **q,
                "question": q["question"].format(**variables),
                "manager": resolve(q.get("manager"), world, variables),
                "checks": [resolve(c, world, variables) for c in q.get("checks", [])],
            }
        )
    return questions


# ── Grading ───────────────────────────────────────────────────────────────────


async def grade(t: Transcript, world: World, q: dict) -> list[C.CheckResult]:
    results = [
        C.check_no_error(t, world, q),
        C.check_loop(t, world, q, allow_turn_limit=q.get("allow_turn_limit", False)),
        C.check_grounding(t, world, q),
    ]
    if t.error:  # no answer to grade
        return results
    for spec in q["checks"]:
        params = {k: v for k, v in spec.items() if k != "type"}
        try:
            outcome = C.CHECKS[spec["type"]](t, world, q, **params)
            results.append(await outcome if inspect.isawaitable(outcome) else outcome)
        except Exception as exc:  # a broken check fails loudly, not the run
            results.append(C.CheckResult(spec["type"], False, f"check error: {exc!r}"))
    return results


def cost(usage: dict, model: str | None) -> float | None:
    price = PRICES.get(model or "")
    if price is None:
        return None
    return sum(usage[k] * price[k] for k in price) / 1_000_000


# ── Running ───────────────────────────────────────────────────────────────────


async def run(args) -> Path:
    snap = Snapshot.load(args.snapshot)
    world = World.build(snap)
    questions = load_questions(world, holdout=args.holdout)
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    if args.tier:
        questions = [q for q in questions if q["tier"] == args.tier]

    if not args.no_build:
        await build_db.build(args.database_url, snap)

    sem = asyncio.Semaphore(args.concurrency)
    rows: list[dict] = []
    async with Harness(snap, build_db.readonly_url(args.database_url)) as harness:

        async def one(q: dict, attempt: int) -> None:
            async with sem:
                t = await harness.ask(q["id"], q["question"], fpl_team_id=q["manager"])
                checks = await grade(t, world, q)
            passed = all(c.passed is not False for c in checks)
            rows.append(
                {
                    "id": q["id"],
                    "attempt": attempt,
                    "tier": q["tier"],
                    "category": q["category"],
                    "holdout": q.get("holdout", False),
                    "question": q["question"],
                    "passed": passed,
                    "checks": [c.to_json() for c in checks],
                    "cost_usd": cost(t.usage, t.model),
                    "model": t.model,
                    **t.to_json(),
                }
            )
            mark = "PASS" if passed else "FAIL"
            print(f"{mark}  {q['id']:<32} {t.seconds:5.1f}s  {t.usage['input']:>7} in")

        await asyncio.gather(*(one(q, a) for q in questions for a in range(1, args.repeats + 1)))

    rows.sort(key=lambda r: ([q["id"] for q in questions].index(r["id"]), r["attempt"]))
    extractor_cost = cost(
        {
            "input": C.EXTRACTOR_USAGE["input"],
            "output": C.EXTRACTOR_USAGE["output"],
            "cache_read": 0,
            "cache_write": 0,
        },
        C.EXTRACTOR_MODEL,
    )
    results = {
        "snapshot": snap.name,
        "started_at": datetime.now(UTC).isoformat(),
        "repeats": args.repeats,
        "extractor_cost_usd": extractor_cost,
        "rows": rows,
    }
    out = RESULTS_DIR / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    previous = json.loads(Path(args.compare).read_text()) if args.compare else None
    summary = summarise(results, previous)
    (out / "summary.md").write_text(summary)
    print("\n" + summary)
    print(f"\nwrote {out}")
    return out


# ── Reporting ─────────────────────────────────────────────────────────────────


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "–"


def _pass_rates(rows: list[dict]) -> dict[str, float]:
    by_id: dict[str, list[bool]] = {}
    for r in rows:
        by_id.setdefault(r["id"], []).append(r["passed"])
    return {i: sum(v) / len(v) for i, v in by_id.items()}


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p * (len(ordered) - 1)))]


def summarise(results: dict, previous: dict | None = None) -> str:
    rows = results["rows"]
    visible = [r for r in rows if not r["holdout"]]
    must = [r for r in visible if r["tier"] == "must_pass"]
    scored = [r for r in visible if r["tier"] == "scored"]
    holdout = [r for r in rows if r["holdout"]]
    kinds = ("input", "output", "cache_read", "cache_write")
    usage = {k: sum(r["usage"][k] for r in rows) for k in kinds}
    prompt_tokens = usage["input"] + usage["cache_read"] + usage["cache_write"]
    agent_cost = sum(r["cost_usd"] or 0 for r in rows)
    seconds = [r["seconds"] for r in rows]

    lines = [
        f"# Gaffer eval — snapshot `{results['snapshot']}`",
        "",
        "| | |",
        "|---|---|",
        f"| must_pass | {_pct(sum(r['passed'] for r in must), len(must))} |",
        f"| scored | {_pct(sum(r['passed'] for r in scored), len(scored))} |",
    ]
    if holdout:
        lines.append(f"| hold-out | {_pct(sum(r['passed'] for r in holdout), len(holdout))} |")
    lines += [
        f"| cost | ${agent_cost + (results['extractor_cost_usd'] or 0):.2f} "
        f"(${agent_cost / max(len(rows), 1):.3f} per answer) |",
        f"| tokens | {usage['input']:,} in, {usage['output']:,} out, "
        f"cache hit {100 * usage['cache_read'] / max(prompt_tokens, 1):.0f}% |",
        f"| latency | p50 {statistics.median(seconds) if seconds else 0:.1f}s, "
        f"p95 {_percentile(seconds, 0.95):.1f}s |",
        f"| repeats | {results['repeats']} |",
        "",
    ]

    if previous:
        now, before = (
            _pass_rates(visible),
            _pass_rates([r for r in previous["rows"] if not r["holdout"]]),
        )
        worse = sorted(i for i in now if i in before and now[i] < before[i])
        better = sorted(i for i in now if i in before and now[i] > before[i])
        lines += [
            "## vs previous run",
            "",
            f"- got worse: {', '.join(worse) or 'none'}",
            f"- got better: {', '.join(better) or 'none'}",
            "",
        ]

    lines += ["## Questions", "", "| | id | tier | why it failed | tokens in | s |"]
    lines.append("|---|---|---|---|---|---|")
    for r in visible:
        failed = [f"{c['type']}: {c['detail']}" for c in r["checks"] if c["passed"] is False]
        why = "<br>".join(f.replace("|", "\\|")[:220] for f in failed)
        mark = "✅" if r["passed"] else "❌"
        attempt = f" #{r['attempt']}" if results["repeats"] > 1 else ""
        lines.append(
            f"| {mark} | {r['id']}{attempt} | {r['tier']} | {why} | {r['usage']['input']:,} | "
            f"{r['seconds']:.0f} |"
        )
    grounding = [
        (r["id"], c["detail"])
        for r in visible
        for c in r["checks"]
        if c["type"] == "grounding" and not c["detail"].startswith("0 ")
    ]
    if grounding:
        lines += ["", "## Ungrounded numbers (report-only)", ""]
        lines += [f"- {i}: {d}" for i, d in grounding]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run The Gaffer answer-quality eval.")
    parser.add_argument("--database-url", required=True, help="throwaway Postgres (superuser)")
    parser.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--only", help="comma-separated question ids")
    parser.add_argument("--tier", choices=["must_pass", "scored"])
    parser.add_argument("--holdout", action="store_true", help="also run the hold-out set")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--compare", help="an earlier results.json")
    parser.add_argument("--no-build", action="store_true", help="reuse the existing database")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
