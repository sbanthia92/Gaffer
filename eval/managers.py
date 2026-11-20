"""
Synthetic FPL managers and mini-leagues, built deterministically from a frozen snapshot.

No real manager's data is recorded or stored. Each manager is a squad picked by fixed
rules from the snapshot's bootstrap, plus the FPL-shaped JSON the app reads for it:
  /entry/{id}/, /entry/{id}/event/{gw}/picks/, /entry/{id}/history/,
  /leagues-classic/{id}/standings/

The shapes mirror the real API — including details the app gets wrong (private
classic leagues have league_type "x"; get_my_fpl_team only keeps "c"), so the eval
sees what production sees.
"""

from dataclasses import dataclass, field

from eval.snapshot import Snapshot

BALANCED = 900001  # a sensible, rules-valid squad; no chips used
THREE_CLUB = 900002  # already owns 3 players from the club of the best-form midfielder
CHIPS_USED = 900003  # used Wildcard, Triple Captain and Bench Boost earlier this season
FREE_HIT = 900004  # Free Hit active in the current gameweek
INVALID = 999999999  # every endpoint 404s
MINI_LEAGUE = 800001

BUDGET = 100.0
_SLOTS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
_STARTERS = {"GKP": 1, "DEF": 4, "MID": 4, "FWD": 2}  # 4-4-2


@dataclass
class Manager:
    entry_id: int
    name: str
    squad: list[dict]  # bootstrap elements, ordered GKP, DEF, MID, FWD
    active_chip: str | None = None
    chips: list[dict] = field(default_factory=list)  # /history/ chips entries
    previous_squad: list[dict] | None = None  # picks for GW-1 (Free Hit only)
    total_points: int = 0

    @property
    def cost(self) -> float:
        return round(sum(p["now_cost"] for p in self.squad) / 10, 1)

    @property
    def bank(self) -> float:
        return round(BUDGET - self.cost, 1)


def _eligible(snap: Snapshot, position: str) -> list[dict]:
    players = [
        p
        for p in snap.bootstrap["elements"]
        if snap.position(p) == position and p["status"] == "a" and p["minutes"] > 0
    ]
    return sorted(players, key=lambda p: (-p["total_points"], p["id"]))


def _club_ok(squad: list[dict], incoming: dict, outgoing: dict | None = None) -> bool:
    same = sum(1 for p in squad if p["team"] == incoming["team"] and p is not outgoing)
    return same < 3


def build_squad(
    snap: Snapshot, forced: list[dict] | None = None, banned_ids: set[int] | None = None
) -> list[dict]:
    """
    Highest total_points squad that fits the rules: 2/5/5/3, max 3 per club, £100m.
    Fill each slot with the best player, then make the cheapest-in-points downgrade
    (points lost per £0.1m saved) until the squad fits the budget. Forced players stay.
    """
    forced = list(forced or [])
    banned_ids = banned_ids or set()
    squad: list[dict] = list(forced)
    for position, count in _SLOTS.items():
        for p in _eligible(snap, position):
            if sum(1 for s in squad if snap.position(s) == position) == count:
                break
            if p["id"] not in banned_ids and p not in squad and _club_ok(squad, p):
                squad.append(p)

    while sum(p["now_cost"] for p in squad) > BUDGET * 10:
        best: tuple[float, dict, dict] | None = None
        for out in squad:
            if out in forced:
                continue
            for cand in _eligible(snap, snap.position(out)):
                saved = out["now_cost"] - cand["now_cost"]
                if (
                    saved <= 0
                    or cand in squad
                    or cand["id"] in banned_ids
                    or not _club_ok(squad, cand, out)
                ):
                    continue
                ratio = (out["total_points"] - cand["total_points"]) / saved
                if best is None or ratio < best[0]:
                    best = (ratio, out, cand)
                break  # _eligible is sorted by points: the first cheaper fit is best
        assert best is not None, "no downgrade fits the budget"
        _, out, cand = best
        squad[squad.index(out)] = cand

    order = list(_SLOTS)
    return sorted(squad, key=lambda p: (order.index(snap.position(p)), -p["total_points"]))


def _starting_xi(snap: Snapshot, squad: list[dict]) -> tuple[list[dict], list[dict]]:
    starters, bench = [], []
    for position, n in _STARTERS.items():
        group = sorted(
            (p for p in squad if snap.position(p) == position),
            key=lambda p: (-p["total_points"], p["id"]),
        )
        starters += group[:n]
        bench += group[n:]
    return starters, bench


def best_form_mid_target(snap: Snapshot, squad: list[dict], budget: float) -> dict:
    """The in-form midfielder a replacement search would surface first."""
    owned = {p["id"] for p in squad}
    candidates = [
        p for p in _eligible(snap, "MID") if p["id"] not in owned and p["now_cost"] / 10 <= budget
    ]
    return max(candidates, key=lambda p: (float(p["form"]), p["total_points"], -p["id"]))


def weakest(snap: Snapshot, squad: list[dict], position: str) -> dict:
    group = [p for p in squad if snap.position(p) == position]
    return min(group, key=lambda p: (p["total_points"], p["id"]))


def _three_club_manager(snap: Snapshot) -> Manager:
    """
    A squad holding 3 non-midfielders from club X, where X is the club of the in-form
    midfielder that replacing the squad's weakest midfielder would surface first. The
    trap: the obvious recommendation is illegal (a 4th player from X).
    """
    mids = sorted(_eligible(snap, "MID"), key=lambda p: (-float(p["form"]), p["id"]))
    for target in mids[:20]:
        club = [
            p
            for pos in ("DEF", "FWD", "GKP")
            for p in _eligible(snap, pos)
            if p["team"] == target["team"]
        ][:3]
        if len(club) < 3:
            continue
        squad = build_squad(snap, forced=club, banned_ids={target["id"]})
        manager = Manager(THREE_CLUB, "Eval Three Club", squad)
        out = weakest(snap, squad, "MID")
        best = best_form_mid_target(snap, squad, out["now_cost"] / 10 + manager.bank)
        if best["team"] == target["team"] and out["team"] != target["team"]:
            return manager
    raise AssertionError("no club makes the 3-per-club trap work in this snapshot")


def _ranked_ids(snap: Snapshot, ranks: list[int]) -> set[int]:
    """Ids of the players at these points ranks in every position (for squad variety)."""
    ids = set()
    for position in _SLOTS:
        ranked = _eligible(snap, position)
        ids |= {ranked[r]["id"] for r in ranks if r < len(ranked)}
    return ids


def build_managers(snap: Snapshot) -> dict[int, Manager]:
    gw = snap.current_gw
    balanced = Manager(BALANCED, "Eval Balanced", build_squad(snap))

    three_club = _three_club_manager(snap)

    chips_used = Manager(
        CHIPS_USED,
        "Eval Chips Used",
        balanced.squad,
        chips=[
            {"name": "wildcard", "event": 3, "time": "2026-09-12T10:00:00Z"},
            {"name": "3xc", "event": 5, "time": "2026-09-26T10:00:00Z"},
            {"name": "bboost", "event": 7, "time": "2026-10-17T10:00:00Z"},
        ],
    )

    free_hit_squad = build_squad(snap, banned_ids=_ranked_ids(snap, [0, 1]))
    free_hit = Manager(
        FREE_HIT,
        "Eval Free Hit",
        free_hit_squad,
        active_chip="freehit",
        chips=[{"name": "freehit", "event": gw, "time": "2026-11-06T10:00:00Z"}],
        previous_squad=balanced.squad,
    )

    managers = {m.entry_id: m for m in (balanced, three_club, chips_used, free_hit)}

    # Mini-league rivals: same rules, picking further down each slot's ranking.
    for i in range(1, 8):
        squad = build_squad(snap, banned_ids=_ranked_ids(snap, [i - 1]))
        rival = Manager(910000 + i, f"Eval Rival {i}", squad)
        managers[rival.entry_id] = rival

    for m in managers.values():
        m.total_points = sum(p["total_points"] for p in m.squad[:11]) + (m.entry_id % 37)
    return managers


# ── FPL-shaped JSON ──────────────────────────────────────────────────────────


def _picks(snap: Snapshot, m: Manager, squad: list[dict], gw: int) -> dict:
    starters, bench = _starting_xi(snap, squad)
    ranked = sorted(starters, key=lambda p: (-p["total_points"], p["id"]))
    captain_id, vice_id = ranked[0]["id"], ranked[1]["id"]
    picks = []
    for i, p in enumerate(starters + bench, start=1):
        captain = p["id"] == captain_id
        picks.append(
            {
                "element": p["id"],
                "position": i,
                "multiplier": (2 if captain else 1) if i <= 11 else 0,
                "is_captain": captain,
                "is_vice_captain": p["id"] == vice_id,
                "element_type": p["element_type"],
                "selling_price": p["now_cost"],
                "purchase_price": p["now_cost"],
            }
        )
    cost = sum(p["now_cost"] for p in squad)
    return {
        "active_chip": m.active_chip if gw == snap.current_gw else None,
        "automatic_subs": [],
        "entry_history": {
            "event": gw,
            "points": sum(p["event_points"] for p in starters),
            "total_points": m.total_points,
            "bank": int(round(BUDGET * 10 - cost)),
            "value": cost,
            "event_transfers": 0,
            "event_transfers_cost": 0,
            "points_on_bench": 0,
        },
        "picks": picks,
    }


def _entry(m: Manager, league_rank: int | None) -> dict:
    classic = [
        {"id": 314, "name": "Overall", "league_type": "s", "scoring": "c", "entry_rank": 1},
    ]
    if league_rank is not None:
        classic.append(
            {
                "id": MINI_LEAGUE,
                "name": "Eval Mini-League",
                "league_type": "x",
                "scoring": "c",
                "entry_rank": league_rank,
                "entry_last_rank": league_rank,
            }
        )
    return {
        "id": m.entry_id,
        "name": m.name,
        "player_first_name": "Eval",
        "player_last_name": "Manager",
        "summary_overall_points": m.total_points,
        "leagues": {"classic": classic},
    }


def _history(snap: Snapshot, m: Manager) -> dict:
    return {
        "current": [{"event": gw, "points": 50} for gw in range(1, snap.current_gw + 1)],
        "past": [],
        "chips": m.chips,
    }


def _league_members(managers: dict[int, Manager]) -> list[Manager]:
    members = [managers[BALANCED]] + [m for e, m in managers.items() if e >= 910000]
    return sorted(members, key=lambda m: (-m.total_points, m.entry_id))


def _league(managers: dict[int, Manager]) -> dict:
    results = [
        {
            "entry": m.entry_id,
            "entry_name": m.name,
            "player_name": f"Manager {m.entry_id}",
            "rank": rank,
            "last_rank": rank,
            "total": m.total_points,
            "event_total": 50,
        }
        for rank, m in enumerate(_league_members(managers), start=1)
    ]
    return {
        "league": {"id": MINI_LEAGUE, "name": "Eval Mini-League"},
        "standings": {"has_next": False, "page": 1, "results": results},
    }


def fpl_routes(snap: Snapshot, managers: dict[int, Manager]) -> dict[str, object]:
    """Every synthetic path the app can request, mapped to its JSON body."""
    gw = snap.current_gw
    ranks = {m.entry_id: r for r, m in enumerate(_league_members(managers), start=1)}
    routes: dict[str, object] = {
        f"/leagues-classic/{MINI_LEAGUE}/standings/": _league(managers),
    }
    for m in managers.values():
        routes[f"/entry/{m.entry_id}/"] = _entry(m, ranks.get(m.entry_id))
        routes[f"/entry/{m.entry_id}/history/"] = _history(snap, m)
        routes[f"/entry/{m.entry_id}/event/{gw}/picks/"] = _picks(snap, m, m.squad, gw)
        previous = m.previous_squad or m.squad
        routes[f"/entry/{m.entry_id}/event/{gw - 1}/picks/"] = _picks(snap, m, previous, gw - 1)
    return routes
