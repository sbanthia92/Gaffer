"""
Unit tests for the eval suite's own code (eval/): the frozen world, synthetic managers,
answer keys, checks and question loading. No model calls — the eval itself is run by
hand (python -m eval.run); these keep its machinery honest in CI.
"""

import json

import httpx
import pytest

from eval import checks as C
from eval import managers as M
from eval.harness import Transcript
from eval.keys import KEYS, World
from eval.replay import FplReplay
from eval.run import load_questions
from eval.snapshot import Snapshot


@pytest.fixture(scope="module")
def world() -> World:
    return World.build(Snapshot.load())


def _transcript(answer: str, tool_calls: list[tuple[str, dict, object]] = (), **kw) -> Transcript:
    """A transcript whose final request holds the given (name, input, result) tool calls."""
    uses, results = [], []
    for i, (name, inp, result) in enumerate(tool_calls):
        uid = inp.pop("_id", f"toolu_{i}")
        uses.append({"type": "tool_use", "id": uid, "name": name, "input": inp})
        results.append({"type": "tool_result", "tool_use_id": uid, "content": json.dumps(result)})
    request = {
        "model": "claude-sonnet-4-6",
        "system": kw.pop("system", [{"type": "text", "text": "prompt"}]),
        "messages": [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": uses},
            {"role": "user", "content": results},
        ],
    }
    usage = {"input_tokens": 10, "output_tokens": 5}
    call = {"kind": "stream", "request": request, "response": {"usage": usage}, "seconds": 1}
    return Transcript("q1", answer, [call], seconds=1.0, **kw)


# ── Snapshot and managers ─────────────────────────────────────────────────────


def test_snapshot_is_between_gameweeks(world):
    snap = world.snap
    assert snap.season_label() == "2026/27"
    assert snap.next_gw == snap.current_gw + 1
    assert all(f"/element-summary/{p['id']}/" in snap.responses for p in snap.players.values())


def test_previous_season_teams_differ_by_exactly_three_clubs(world):
    # _new_to_league_this_season only trusts a diff of 20 clubs with at most 3 new ones.
    previous = {t["name"] for t in world.snap.previous_season_teams}
    current = {t["name"] for t in world.snap.bootstrap["teams"]}
    assert len(previous) == len(current) == 20
    assert len(current - previous) == 3


def test_every_synthetic_squad_is_legal(world):
    for manager in world.managers.values():
        assert C.squad_problems(world, manager.squad) == [], manager.name


def test_three_club_trap_is_armed(world):
    """The best-form replacement for the weakest midfielder is from a full club."""
    m = world.managers[M.THREE_CLUB]
    out = M.weakest(world.snap, m.squad, "MID")
    target = M.best_form_mid_target(world.snap, m.squad, out["now_cost"] / 10 + m.bank)
    assert world.snap.team_name(target) in KEYS["full_clubs"](world, manager=M.THREE_CLUB)
    assert C.transfer_problems(world, M.THREE_CLUB, [out], [target], "MID")


def test_private_league_has_real_fpl_league_type(world):
    """Real FPL marks private classic leagues "x"; the synthetic data must match."""
    routes = M.fpl_routes(world.snap, world.managers)
    leagues = routes[f"/entry/{M.BALANCED}/"]["leagues"]["classic"]
    assert {lg["league_type"] for lg in leagues if lg["id"] == M.MINI_LEAGUE} == {"x"}


# ── Replay ────────────────────────────────────────────────────────────────────


async def test_replay_serves_snapshot_and_404s_the_rest(world):
    replay = FplReplay(world.snap)
    async with replay.client() as client:
        assert (await client.get("/bootstrap-static/")).json()["events"]
        gw = world.snap.next_gw
        fixtures = (await client.get("/fixtures/", params={"event": gw})).json()
        assert fixtures and {f["event"] for f in fixtures} == {gw}
        r = await client.get(f"/entry/{M.INVALID}/")
        assert r.status_code == 404
        with pytest.raises(httpx.HTTPStatusError):
            r.raise_for_status()
    assert replay.misses == [f"https://fantasy.premierleague.com/api/entry/{M.INVALID}/"]


# ── Questions ─────────────────────────────────────────────────────────────────


def test_every_question_resolves(world):
    """Each key and placeholder computes on the current snapshot; ids are unique."""
    questions = load_questions(world, holdout=True)
    assert len({q["id"] for q in questions}) == len(questions)
    for q in questions:
        assert "{" not in q["question"], q["id"]
        assert q["tier"] in ("must_pass", "scored")
        for check in q["checks"]:
            assert check["type"] in C.CHECKS, (q["id"], check["type"])


# ── Checks ────────────────────────────────────────────────────────────────────


def test_mentions_ignores_accents_and_tags(world):
    t = _transcript("Sell [[Odegaard]] and buy [[Wirtz]].")
    assert C.check_mentions(t, world, {}, values=["Ødegaard", "Wirtz"]).passed
    assert not C.check_mentions(t, world, {}, values=["Wirtzy"]).passed


def test_loop_flags_repeats_refetches_and_turn_cap(world):
    clean = _transcript("ok", [("get_my_fpl_team", {"_id": "prefetch_squad"}, {})])
    assert C.check_loop(clean, world, {}).passed

    messy = _transcript(
        "ok",
        [
            ("get_my_fpl_team", {"_id": "prefetch_squad"}, {}),
            ("get_my_fpl_team", {}, {}),
            ("get_fixtures", {"next_n": 5}, {}),
            ("get_fixtures", {"next_n": 5}, {}),
        ],
        system=[{"type": "text", "text": "prompt"}, {"type": "text", "text": "turn limit"}],
    )
    detail = C.check_loop(messy, world, {}).detail
    assert "turn cap" in detail and "repeated" in detail and "get_my_fpl_team" in detail
    assert C.check_loop(messy, world, {}, allow_turn_limit=True).passed is False


def test_grounding_allows_tool_numbers_and_their_differences(world):
    t = _transcript(
        "He costs £8.5m, £1.5m more than the 7.0 option, and has 73 points.",
        [("search_players_by_criteria", {}, {"players": [{"price": 8.5}, {"price": 7.0}]})],
    )
    result = C.check_grounding(t, world, {"question": "q"})
    assert result.passed is None  # report-only
    assert result.detail == "1 ungrounded: 73"


def test_promotion_only_fires_for_clubs_not_new_this_season(world):
    t = _transcript("Leeds are a newly promoted side. Coventry were promoted too.")
    new = KEYS["new_to_league"](world)
    assert not C.check_promotion(t, world, {}, clubs=["Leeds"], new=new).passed
    assert C.check_promotion(t, world, {}, clubs=["Coventry City"], new=new).passed


def test_first_player_reads_the_verdict(world):
    t = _transcript("✅ Captain [[Isak]] over [[Haaland]].")
    assert C.check_first_player(t, world, {}, allowed=["Isak"]).passed
    assert not C.check_first_player(t, world, {}, allowed=["Haaland"]).passed


def test_ends_cleanly(world):
    assert not C.check_ends_cleanly(_transcript("Data... Let me fetch those."), world, {}).passed
    assert C.check_ends_cleanly(_transcript("Captain Isak."), world, {}).passed


def test_chips_check_uses_the_managers_history(world):
    good = _transcript(
        "You've already used your Wildcard, Triple Captain and Bench Boost. "
        "Your Free Hit is still available."
    )
    assert C.check_chips(good, world, {}, manager=M.CHIPS_USED).passed
    bad = _transcript("You still have your Triple Captain and Free Hit.")
    assert not C.check_chips(bad, world, {}, manager=M.CHIPS_USED).passed


def test_transfer_problems_catch_rule_breaks(world):
    m = world.managers[M.BALANCED]
    snap = world.snap
    out = M.weakest(snap, m.squad, "MID")
    others = [p for p in snap.players.values() if p["id"] not in {s["id"] for s in m.squad}]
    fwd = next(p for p in others if snap.position(p) == "FWD")
    assert any("positions" in p for p in C.transfer_problems(world, M.BALANCED, [out], [fwd], None))
    owned = next(p for p in m.squad if snap.position(p) == "MID" and p is not out)
    assert any("already" in p for p in C.transfer_problems(world, M.BALANCED, [out], [owned], None))
    pricey = max((p for p in others if snap.position(p) == "MID"), key=lambda p: p["now_cost"])
    assert pricey["now_cost"] / 10 > out["now_cost"] / 10 + m.bank
    problems = C.transfer_problems(world, M.BALANCED, [out], [pricey], None)
    assert any("costs" in p for p in problems)
