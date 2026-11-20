"""
A frozen copy of the FPL API, recorded once by eval/record.py and replayed in every run.

Layout of a snapshot directory (eval/snapshots/<name>/):
  fpl.json.gz                 {"recorded_at": ISO-8601, "responses": {path: json}}
  previous_season_teams.json  last season's Premier League clubs (see record.py)
"""

import gzip
import json
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from pathlib import Path

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
DEFAULT_SNAPSHOT = "2026-27-gw10"

_POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


@dataclass
class Snapshot:
    recorded_at: datetime
    responses: dict[str, object]
    previous_season_teams: list[str] | None = None
    name: str = ""
    _by_id: dict[int, dict] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, name: str = DEFAULT_SNAPSHOT) -> "Snapshot":
        directory = SNAPSHOTS_DIR / name
        with gzip.open(directory / "fpl.json.gz", "rt", encoding="utf-8") as f:
            raw = json.load(f)
        prev_path = directory / "previous_season_teams.json"
        previous = json.loads(prev_path.read_text())["teams"] if prev_path.exists() else None
        return cls(
            recorded_at=datetime.fromisoformat(raw["recorded_at"]),
            responses=raw["responses"],
            previous_season_teams=previous,
            name=name,
        )

    # ── Convenience views used by keys, managers and checks ──────────────────

    @property
    def bootstrap(self) -> dict:
        return self.responses["/bootstrap-static/"]  # type: ignore[return-value]

    @property
    def fixtures(self) -> list[dict]:
        return self.responses["/fixtures/"]  # type: ignore[return-value]

    @cached_property
    def teams(self) -> dict[int, dict]:
        return {t["id"]: t for t in self.bootstrap["teams"]}

    @cached_property
    def players(self) -> dict[int, dict]:
        return {p["id"]: p for p in self.bootstrap["elements"]}

    @property
    def current_gw(self) -> int:
        events = self.bootstrap["events"]
        return next(
            (e["id"] for e in events if e["is_current"]),
            next((e["id"] for e in events if e["is_next"]), 1),
        )

    @property
    def next_gw(self) -> int:
        return next(e["id"] for e in self.bootstrap["events"] if e["is_next"])

    def position(self, player: dict) -> str:
        return _POSITIONS[player["element_type"]]

    def team_name(self, player: dict) -> str:
        return self.teams[player["team"]]["name"]

    def season_label(self) -> str:
        """'2026/27' — the same derivation as pipeline/etl_v2._current_season_label."""
        year = int(self.bootstrap["events"][0]["deadline_time"][:4])
        return f"{year}/{str(year + 1)[2:]}"
