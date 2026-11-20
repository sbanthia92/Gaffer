"""
Checks: each takes the transcript of one answered question and returns a CheckResult.

Everything is decided in code against the frozen data. The one exception is
`transfer_rules` / `squad_rules`, where a small model first *extracts* which players the
answer recommends (free text can't be parsed reliably otherwise); the rule checks on
those players are still code.

`passed` is True/False, or None for report-only checks (grounding) that don't count.
"""

import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

import anthropic

from eval import managers as M
from eval.harness import Transcript
from eval.keys import World
from server.tools.fpl import _find_player

EXTRACTOR_MODEL = "claude-haiku-5-5"
EXTRACTOR_USAGE = {"input": 0, "output": 0}  # summed over a run, for the cost report

_PROMOTION = re.compile(
    r"promot|newcomers|newly[- ]up|back in the (premier league|top flight)|"
    r"first season (back|in the)",
    re.IGNORECASE,
)
_UNFINISHED = re.compile(
    r"\b(let me|i'll|i will|i'm going to)\s+(now\s+)?(fetch|check|grab|pull|look|search|get)\b",
    re.IGNORECASE,
)


@dataclass
class CheckResult:
    type: str
    passed: bool | None
    detail: str = ""

    def to_json(self) -> dict:
        return {"type": self.type, "passed": self.passed, "detail": self.detail}


def normalise(text: str) -> str:
    """Case-, accent- and markup-insensitive text for matching names."""
    text = text.replace("[[", "").replace("]]", "")
    text = text.translate(str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "ß": "ss", "’": "'"}))
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def _contains(answer: str, spelling: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(normalise(spelling)) + r"(?!\w)"
    return re.search(pattern, normalise(answer)) is not None


def _found(answer: str, group: list[str]) -> bool:
    return any(_contains(answer, s) for s in group)


def _groups(values) -> list[list[str]]:
    return [v if isinstance(v, list) else [v] for v in values]


def player_tokens(answer: str) -> list[str]:
    """[[Name]] tags in order — the prompt makes the model tag every player it names."""
    return re.findall(r"\[\[([^\]]+)\]\]", answer)


# ── Always-on checks ──────────────────────────────────────────────────────────


def check_no_error(t: Transcript, world: World, q: dict) -> CheckResult:
    if t.error:
        return CheckResult("no_error", False, t.error[:300])
    if not t.answer.strip():
        return CheckResult("no_error", False, "empty answer")
    return CheckResult("no_error", True)


def check_loop(t: Transcript, world: World, q: dict, allow_turn_limit: bool = False):
    problems = []
    if t.turn_limit_hit and not allow_turn_limit:
        problems.append(f"hit the tool-turn cap ({t.tool_turns} turns)")
    seen: set[str] = set()
    for c in t.model_tool_calls:
        signature = c.name + json.dumps(c.input, sort_keys=True)
        if signature in seen:
            problems.append(f"repeated identical call {c.name}({json.dumps(c.input)})")
        seen.add(signature)
    # The prompt says pre-loaded data must be used, not fetched again (v0.40 fix). Only
    # pre-fetches that succeeded count: a failed one leaves the model free to retry.
    prefetched = {c.name for c in t.tool_calls if c.prefetched}
    refetched = sorted({c.name for c in t.model_tool_calls if c.name in prefetched})
    if refetched:
        problems.append(f"re-called pre-fetched tools: {', '.join(refetched)}")
    return CheckResult("loop", not problems, "; ".join(problems))


_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
# Small integers (counts, formation slots) and FPL rule constants need no source.
_RULE_NUMBERS = {11, 15, 19, 20, 38, 100}


def _numbers(text: str) -> set[float]:
    return {float(n) for n in _NUMBER.findall(text.replace(",", ""))}


def check_grounding(t: Transcript, world: World, q: dict) -> CheckResult:
    """Report-only: numbers in the answer that no tool result (or the question) contains."""
    sources = _numbers(" ".join(c.result for c in t.tool_calls) + " " + q["question"])
    rounded = sources | {round(s, 1) for s in sources} | {round(s) for s in sources}
    ungrounded = []
    for x in sorted(_numbers(t.answer)):
        if x <= 10 and x == int(x) or x in _RULE_NUMBERS or x in rounded:
            continue
        # A sum or difference of two tool numbers (e.g. a price gap) is still grounded.
        if any(round(x - s, 1) in rounded or round(s - x, 1) in rounded for s in sources):
            continue
        ungrounded.append(x)
    shown = ", ".join(f"{x:g}" for x in ungrounded[:15])
    return CheckResult("grounding", None, f"{len(ungrounded)} ungrounded: {shown}".strip(": "))


# ── Checks a question opts into ────────────────────────────────────────────────


def check_tools(
    t: Transcript,
    world: World,
    q: dict,
    expect_any: list[str] | None = None,
    expect_all: list[str] | None = None,
    forbid: list[str] | None = None,
    args: list[dict] | None = None,
) -> CheckResult:
    called = [c.name for c in t.model_tool_calls]
    problems = []
    if expect_any and not set(expect_any) & set(called):
        problems.append(f"called none of {expect_any}")
    for name in expect_all or []:
        if name not in called:
            problems.append(f"did not call {name}")
    for name in forbid or []:
        if name in called:
            problems.append(f"called forbidden {name}")
    for rule in args or []:
        calls = [c for c in t.model_tool_calls if c.name == rule["tool"]]
        if rule.get("required") and not calls:
            problems.append(f"did not call {rule['tool']}")
        for c in calls:
            for key, want in rule["equals"].items():
                got = c.input.get(key)
                if str(got).casefold() != str(want).casefold():
                    problems.append(f"{rule['tool']} called with {key}={got!r}, want {want!r}")
    return CheckResult("tools", not problems, "; ".join(problems) or f"called {called}")


def check_mentions(
    t: Transcript, world: World, q: dict, values: list, mode: str = "all", at_least: int = 1
) -> CheckResult:
    groups = _groups(values)
    found = [g[0] for g in groups if _found(t.answer, g)]
    missing = [g[0] for g in groups if not _found(t.answer, g)]
    need = {"all": len(groups), "any": 1, "at_least": at_least}[mode]
    detail = f"found {found}" + (f"; missing {missing}" if missing else "")
    return CheckResult("mentions", len(found) >= need, detail)


def check_not_mentions(t: Transcript, world: World, q: dict, values: list) -> CheckResult:
    hits = [g[0] for g in _groups(values) if _found(t.answer, g)]
    return CheckResult("not_mentions", not hits, f"mentioned {hits}" if hits else "")


def check_regex_any(t: Transcript, world: World, q: dict, patterns: list[str]) -> CheckResult:
    hit = next((p for p in patterns if re.search(p, t.answer, re.IGNORECASE)), None)
    return CheckResult("regex_any", hit is not None, f"matched {hit!r}" if hit else "no match")


def check_regex_none(t: Transcript, world: World, q: dict, patterns: list[str]) -> CheckResult:
    for p in patterns:
        m = re.search(p, t.answer, re.IGNORECASE)
        if m:
            return CheckResult("regex_none", False, f"matched {m.group(0)!r}")
    return CheckResult("regex_none", True)


def check_promotion(t: Transcript, world: World, q: dict, clubs: list[str], new: list[str]):
    """From the old scripts/eval_stale_knowledge.py: a club this season's data says was
    NOT promoted must not be described as promoted."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", t.answer)
    claims = [
        s.strip()[:200]
        for club in clubs
        if club not in new
        for s in sentences
        if _contains(s, club) and _PROMOTION.search(s)
    ]
    return CheckResult("promotion", not claims, " | ".join(claims))


def check_first_player(t: Transcript, world: World, q: dict, allowed: list) -> CheckResult:
    """The verdict names a player first; it must be one of the allowed players."""
    tokens = player_tokens(t.answer)
    if not tokens:
        return CheckResult("first_player", False, "no [[Player]] tag in the answer")
    ok = any(_found(tokens[0], g) for g in _groups(allowed))
    return CheckResult("first_player", ok, f"first player {tokens[0]!r}")


def check_ends_cleanly(t: Transcript, world: World, q: dict) -> CheckResult:
    """From the v0.102 fix: an answer must not end by announcing a fetch it never makes."""
    tail = t.answer.strip()[-400:]
    m = _UNFINISHED.search(tail)
    return CheckResult("ends_cleanly", m is None, f"ends with {m.group(0)!r}" if m else "")


def check_unavailable_or_grounded(t: Transcript, world: World, q: dict, patterns: list[str]):
    """Either the answer says the data isn't available, or every number in it is grounded."""
    if any(re.search(p, t.answer, re.IGNORECASE) for p in patterns):
        return CheckResult("unavailable_or_grounded", True, "says the data is unavailable")
    g = check_grounding(t, world, q)
    clean = g.detail.startswith("0 ")
    return CheckResult("unavailable_or_grounded", clean, g.detail)


_CHIP_NAMES = {
    "3xc": ["triple captain", "TC"],
    "bboost": ["bench boost", "BB"],
    "freehit": ["free hit", "FH"],
    "wildcard": ["wildcard", "WC"],
}
_USED_WORDS = re.compile(
    r"used|played|spent|unavailable|not available|no longer|gone|already|activated", re.I
)


def check_chips(t: Transcript, world: World, q: dict, manager: int) -> CheckResult:
    """Every chip the manager used is described as used; unused ones are mentioned."""
    used = {c["name"] for c in world.managers[manager].chips}
    sentences = re.split(r"(?<=[.!?])\s+|\n+", t.answer)
    problems = []
    for chip, names in _CHIP_NAMES.items():
        about = [s for s in sentences if any(_contains(s, n) for n in names)]
        if chip in used and not any(_USED_WORDS.search(s) for s in about):
            problems.append(f"{names[0]} not described as used")
        if chip not in used and not about:
            problems.append(f"{names[0]} (available) not mentioned")
    return CheckResult("chips", not problems, "; ".join(problems))


# ── Rule checks on extracted recommendations ───────────────────────────────────

_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "transfers_out": {"type": "array", "items": {"type": "string"}},
        "transfers_in": {"type": "array", "items": {"type": "string"}},
        "full_squad": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["transfers_out", "transfers_in", "full_squad"],
    "additionalProperties": False,
}
_EXTRACT_PROMPT = (
    "Below is an FPL assistant's answer. Extract only what it RECOMMENDS the user do — "
    "not players mentioned as rejected, ineligible, alternatives ruled out, or for "
    "context.\n"
    "- transfers_out: players it recommends selling.\n"
    "- transfers_in: players it recommends buying as its main recommendation (if it "
    "gives ranked options, only the first choice for each transfer).\n"
    "- full_squad: if it proposes a complete 15-player squad, all 15 names; else [].\n"
    "Use the player names exactly as written.\n\n<answer>\n{answer}\n</answer>"
)


async def extract_recommendations(answer: str) -> dict:
    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=EXTRACTOR_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": _EXTRACT_PROMPT.format(answer=answer)}],
        output_config={"format": {"type": "json_schema", "schema": _EXTRACT_SCHEMA}},
    )
    text = next(b.text for b in response.content if b.type == "text")
    EXTRACTOR_USAGE["input"] += response.usage.input_tokens
    EXTRACTOR_USAGE["output"] += response.usage.output_tokens
    return json.loads(text)


def _resolve(world: World, names: list[str]) -> tuple[list[dict], list[str]]:
    elements = world.snap.bootstrap["elements"]
    found, unknown = [], []
    for name in names:
        p = _find_player(elements, name)
        (found.append(p) if p else unknown.append(name))
    return found, unknown


def transfer_problems(
    world: World, manager: int, outs: list[dict], ins: list[dict], out_position: str | None
) -> list[str]:
    m = world.managers[manager]
    snap = world.snap
    owned = {p["id"] for p in m.squad}
    problems = []
    for p in ins:
        if p["id"] in owned:
            problems.append(f"{p['web_name']} is already in the squad")
    for p in outs:
        if p["id"] not in owned:
            problems.append(f"sells {p['web_name']}, who isn't in the squad")
    positions_out = sorted(snap.position(p) for p in outs)
    if not positions_out and out_position:
        positions_out = [out_position]
    positions_in = sorted(snap.position(p) for p in ins)
    if positions_out and positions_in and positions_in != positions_out[: len(positions_in)]:
        problems.append(f"positions don't match: out {positions_out}, in {positions_in}")
    after = [p for p in m.squad if p["id"] not in {o["id"] for o in outs}] + ins
    for club in {p["team"] for p in ins}:
        n = sum(1 for p in after if p["team"] == club)
        if n > 3:
            problems.append(f"{n} players from {snap.teams[club]['name']} after the transfer")
    budget = m.bank + sum(p["now_cost"] for p in outs) / 10
    cost = sum(p["now_cost"] for p in ins) / 10
    if outs and cost > budget + 1e-9:
        problems.append(f"costs £{cost:.1f}m with £{budget:.1f}m available")
    return problems


def squad_problems(world: World, squad: list[dict], budget: float = M.BUDGET) -> list[str]:
    snap = world.snap
    problems = []
    if len({p["id"] for p in squad}) != 15:
        problems.append(f"{len({p['id'] for p in squad})} distinct players, not 15")
    counts = {pos: sum(1 for p in squad if snap.position(p) == pos) for pos in M._SLOTS}
    if counts != M._SLOTS:
        problems.append(f"positions {counts}, need {M._SLOTS}")
    for club in {p["team"] for p in squad}:
        n = sum(1 for p in squad if p["team"] == club)
        if n > 3:
            problems.append(f"{n} players from {snap.teams[club]['name']}")
    cost = sum(p["now_cost"] for p in squad) / 10
    if cost > budget + 1e-9:
        problems.append(f"costs £{cost:.1f}m, budget £{budget:.1f}m")
    return problems


async def check_transfer_rules(
    t: Transcript, world: World, q: dict, manager: int, out_position: str | None = None
) -> CheckResult:
    rec = await extract_recommendations(t.answer)
    outs, unknown_out = _resolve(world, rec["transfers_out"])
    ins, unknown_in = _resolve(world, rec["transfers_in"])
    problems = [f"unknown player {n!r}" for n in unknown_out + unknown_in]
    problems += transfer_problems(world, manager, outs, ins, out_position)
    detail = f"out {rec['transfers_out']} in {rec['transfers_in']}"
    if not ins:
        return CheckResult("transfer_rules", True, detail + " (no transfer recommended)")
    return CheckResult("transfer_rules", not problems, detail + "; " + "; ".join(problems))


async def check_squad_rules(
    t: Transcript, world: World, q: dict, manager: int | None = None
) -> CheckResult:
    rec = await extract_recommendations(t.answer)
    squad, unknown = _resolve(world, rec["full_squad"])
    problems = [f"unknown player {n!r}" for n in unknown]
    budget = (
        M.BUDGET if manager is None else world.managers[manager].cost + world.managers[manager].bank
    )
    problems += squad_problems(world, squad, budget)
    return CheckResult("squad_rules", not problems, "; ".join(problems) or "valid squad")


CHECKS: dict[str, Callable] = {
    "tools": check_tools,
    "mentions": check_mentions,
    "not_mentions": check_not_mentions,
    "regex_any": check_regex_any,
    "regex_none": check_regex_none,
    "promotion": check_promotion,
    "first_player": check_first_player,
    "ends_cleanly": check_ends_cleanly,
    "unavailable_or_grounded": check_unavailable_or_grounded,
    "chips": check_chips,
    "transfer_rules": check_transfer_rules,
    "squad_rules": check_squad_rules,
}
ALWAYS = (check_no_error, check_loop, check_grounding)
