"""
Answer keys and question inputs, computed from the frozen snapshot — never hand-typed.

Each key is a function of (World, **params). Questions refer to them by name in
eval/questions.yaml, either to fill a placeholder in the question text (`vars`) or as
the expected value of a check. When the snapshot changes, the keys change with it.
"""

from dataclasses import dataclass, field

from eval import managers as M
from eval.snapshot import Snapshot

# How the model may spell a club that FPL abbreviates. Spellings only, not facts.
_CLUB_ALIASES = {
    "Man City": ["Manchester City", "Man City", "MCI"],
    "Man Utd": ["Manchester United", "Man Utd", "Man United", "MUN"],
    "Spurs": ["Tottenham", "Spurs", "TOT"],
    "Nott'm Forest": ["Nottingham Forest", "Nott'm Forest", "Forest", "NFO"],
    "Hull City": ["Hull"],
    "Ipswich Town": ["Ipswich"],
    "Coventry City": ["Coventry"],
    "Newcastle": ["Newcastle"],
    "Brighton": ["Brighton"],
}


@dataclass
class World:
    """Everything a key can read: the snapshot and the synthetic managers built from it."""

    snap: Snapshot
    managers: dict[int, M.Manager] = field(default_factory=dict)

    @classmethod
    def build(cls, snap: Snapshot) -> "World":
        return cls(snap, M.build_managers(snap))


def club_spellings(name: str) -> list[str]:
    return _CLUB_ALIASES.get(name, [name])


def _team_id(world: World, name: str) -> int:
    return next(t["id"] for t in world.snap.bootstrap["teams"] if t["name"] == name)


def _upcoming(world: World, team_id: int) -> list[dict]:
    fixtures = [
        f
        for f in world.snap.fixtures
        if not f["finished"] and f["event"] is not None and team_id in (f["team_h"], f["team_a"])
    ]
    return sorted(fixtures, key=lambda f: (f["event"], f["kickoff_time"] or ""))


# ── Keys ──────────────────────────────────────────────────────────────────────


def season_label(world: World) -> list[str]:
    label = world.snap.season_label()
    return [label, label.replace("/", "-"), label.replace("/", "–")]


def next_opponents(world: World, team: str, n: int = 1) -> list[list[str]]:
    """The next n opponents, each as a list of acceptable spellings."""
    tid = _team_id(world, team)
    out = []
    for f in _upcoming(world, tid)[:n]:
        opp = f["team_a"] if f["team_h"] == tid else f["team_h"]
        out.append(club_spellings(world.snap.teams[opp]["name"]))
    return out


def top_players(world: World, position: str, n: int = 3, field: str = "total_points") -> list:
    players = [p for p in world.snap.bootstrap["elements"] if world.snap.position(p) == position]
    ranked = sorted(players, key=lambda p: (-float(p[field]), p["id"]))
    return [[p["web_name"]] for p in ranked[:n]]


def table_rank(world: World, team: str) -> int:
    """League position computed from finished fixtures (points, goal difference, goals)."""
    table = {t["id"]: [0, 0, 0] for t in world.snap.bootstrap["teams"]}  # pts, gd, gf
    for f in world.snap.fixtures:
        if not f["finished"]:
            continue
        h, a, hg, ag = f["team_h"], f["team_a"], f["team_h_score"], f["team_a_score"]
        table[h][1] += hg - ag
        table[a][1] += ag - hg
        table[h][2] += hg
        table[a][2] += ag
        if hg > ag:
            table[h][0] += 3
        elif ag > hg:
            table[a][0] += 3
        else:
            table[h][0] += 1
            table[a][0] += 1
    order = sorted(table, key=lambda t: (-table[t][0], -table[t][1], -table[t][2]))
    return order.index(_team_id(world, team)) + 1


def ordinal_spellings(n: int) -> list[str]:
    words = {
        1: "first",
        2: "second",
        3: "third",
        4: "fourth",
        5: "fifth",
        6: "sixth",
        7: "seventh",
        8: "eighth",
        9: "ninth",
        10: "tenth",
    }
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    spellings = [f"{n}{suffix}", f"#{n}", f"P{n}", f"position {n}", f"rank {n}"]
    if n in words:
        spellings.append(words[n])
    if n == 1:
        spellings += ["top of the", "top of the table", "league leaders"]
    return spellings


def table_rank_spellings(world: World, team: str) -> list[str]:
    return ordinal_spellings(table_rank(world, team))


def squad_names(world: World, manager: int) -> list[list[str]]:
    return [[p["web_name"]] for p in world.managers[manager].squad]


def squad_attackers(world: World, manager: int, n: int = 2) -> list[str]:
    """The manager's n highest-scoring midfielders/forwards — natural captain options."""
    squad = world.managers[manager].squad
    attackers = [p for p in squad if world.snap.position(p) in ("MID", "FWD")]
    ranked = sorted(attackers, key=lambda p: (-p["total_points"], p["id"]))
    return [p["web_name"] for p in ranked[:n]]


def weakest_mid(world: World, manager: int) -> str:
    return M.weakest(world.snap, world.managers[manager].squad, "MID")["web_name"]


def full_clubs(world: World, manager: int) -> list[str]:
    """Clubs the manager already has 3 players from."""
    counts: dict[str, int] = {}
    for p in world.managers[manager].squad:
        name = world.snap.team_name(p)
        counts[name] = counts.get(name, 0) + 1
    return sorted(c for c, n in counts.items() if n >= 3)


def injured_player(world: World) -> str:
    """The most-owned player flagged injured or doubtful."""
    flagged = [p for p in world.snap.bootstrap["elements"] if p["status"] in ("i", "d")]
    best = max(flagged, key=lambda p: (float(p["selected_by_percent"]), -p["id"]))
    return best["web_name"]


def ambiguous_surname(world: World) -> str:
    """A surname two regular players at different clubs share (both 300+ minutes)."""
    by_name: dict[str, list[dict]] = {}
    for p in world.snap.bootstrap["elements"]:
        if p["minutes"] >= 300 and p["web_name"] == p["second_name"]:
            by_name.setdefault(p["second_name"], []).append(p)
    shared = {
        n: ps for n, ps in by_name.items() if len({p["team"] for p in ps}) >= 2 and len(ps) == 2
    }
    name = max(shared, key=lambda n: (sum(p["total_points"] for p in shared[n]), n))
    return name


def ambiguous_clubs(world: World, name: str) -> list[list[str]]:
    teams = {
        world.snap.team_name(p)
        for p in world.snap.bootstrap["elements"]
        if p["second_name"] == name and p["minutes"] >= 300
    }
    return [club_spellings(t) for t in sorted(teams)]


def fdr5_player(world: World) -> str:
    """The highest-scoring attacker whose next fixture is FDR 5 for his team."""
    nxt = world.snap.next_gw
    hard: set[int] = set()
    for f in world.snap.fixtures:
        if f["event"] == nxt:
            if f["team_h_difficulty"] == 5:
                hard.add(f["team_h"])
            if f["team_a_difficulty"] == 5:
                hard.add(f["team_a"])
    candidates = [
        p
        for p in world.snap.bootstrap["elements"]
        if p["team"] in hard and world.snap.position(p) in ("MID", "FWD") and p["status"] == "a"
    ]
    return max(candidates, key=lambda p: (p["total_points"], -p["id"]))["web_name"]


def player_club(world: World, name: str) -> str:
    p = next(p for p in world.snap.bootstrap["elements"] if p["web_name"] == name)
    return world.snap.team_name(p)


def zero_point_starter(world: World) -> str:
    """A widely owned player who played 60+ minutes in the last gameweek and scored 0."""
    gw = world.snap.current_gw
    candidates = []
    for p in world.snap.bootstrap["elements"]:
        summary = world.snap.responses.get(f"/element-summary/{p['id']}/") or {}
        rows = [h for h in summary.get("history", []) if h["round"] == gw]
        minutes = sum(h["minutes"] for h in rows)
        if rows and minutes >= 60 and sum(h["total_points"] for h in rows) == 0:
            candidates.append(p)
    best = max(candidates, key=lambda p: (float(p["selected_by_percent"]), -p["id"]))
    return best["web_name"]


def price_risers(world: World, n: int = 5) -> list[list[str]]:
    """Most net transfers in since the deadline — what get_price_changes ranks first."""
    ranked = sorted(
        world.snap.bootstrap["elements"],
        key=lambda p: (-(p["transfers_in_event"] - p["transfers_out_event"]), p["id"]),
    )
    return [[p["web_name"]] for p in ranked[:n]]


def easiest_fixture_runs(world: World, gws: int = 5, n: int = 5) -> list[list[str]]:
    """Clubs with the lowest average FDR over the next `gws` gameweeks."""
    start = world.snap.next_gw
    window = range(start, start + gws)
    scores: dict[int, list[int]] = {t: [] for t in world.snap.teams}
    for f in world.snap.fixtures:
        if f["event"] in window:
            scores[f["team_h"]].append(f["team_h_difficulty"])
            scores[f["team_a"]].append(f["team_a_difficulty"])
    avg = {t: sum(s) / len(s) for t, s in scores.items() if s}
    ranked = sorted(avg, key=lambda t: (avg[t], t))
    return [club_spellings(world.snap.teams[t]["name"]) for t in ranked[:n]]


def league_rank(world: World, manager: int) -> int:
    members = M._league_members(world.managers)
    return next(i for i, m in enumerate(members, 1) if m.entry_id == manager)


def new_to_league(world: World) -> list[str]:
    if not world.snap.previous_season_teams:
        return []
    previous = {t["name"] for t in world.snap.previous_season_teams}
    return sorted(t["name"] for t in world.snap.bootstrap["teams"] if t["name"] not in previous)


KEYS = {
    f.__name__: f
    for f in (
        season_label,
        next_opponents,
        top_players,
        table_rank,
        table_rank_spellings,
        squad_names,
        squad_attackers,
        weakest_mid,
        full_clubs,
        injured_player,
        ambiguous_surname,
        ambiguous_clubs,
        fdr5_player,
        player_club,
        zero_point_starter,
        price_risers,
        easiest_fixture_runs,
        league_rank,
        new_to_league,
    )
}
