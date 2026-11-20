"""
Re-record the frozen FPL data the eval replays. Run deliberately — never from CI:

    python -m eval.record --name 2026-27-gw11

Pick a quiet moment (a gameweek finished, before the next deadline) so the data is
internally consistent. Recording a new snapshot changes the world every question sees,
so scores from different snapshots must not be compared: bump DEFAULT_SNAPSHOT in
eval/snapshot.py in its own PR and re-baseline.

Recorded: /bootstrap-static/, /fixtures/ and /element-summary/{id}/ for every player.
Not recorded: manager entries and mini-leagues — those are synthetic (eval/managers.py),
so no real manager's data is stored.

previous_season_teams.json is copied from an existing snapshot if present. The FPL API
has no endpoint for last season's clubs, so when the season rolls over, write the new
file by hand from last season's final bootstrap (or the production `teams` table).
"""

import argparse
import asyncio
import gzip
import json
import shutil
from datetime import UTC, datetime

import httpx

from eval.snapshot import DEFAULT_SNAPSHOT, SNAPSHOTS_DIR

_FPL_BASE = "https://fantasy.premierleague.com/api"
_CONCURRENCY = 6  # be polite to the FPL API — ~700 element-summary requests


async def _get(client: httpx.AsyncClient, path: str, attempts: int = 4) -> object:
    for attempt in range(attempts):
        try:
            r = await client.get(f"{_FPL_BASE}{path}")
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError):
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(2**attempt)
    raise AssertionError("unreachable")


async def record(name: str) -> None:
    recorded_at = datetime.now(UTC)
    responses: dict[str, object] = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        bootstrap = await _get(client, "/bootstrap-static/")
        responses["/bootstrap-static/"] = bootstrap
        responses["/fixtures/"] = await _get(client, "/fixtures/")

        sem = asyncio.Semaphore(_CONCURRENCY)

        async def summary(pid: int) -> None:
            async with sem:
                responses[f"/element-summary/{pid}/"] = await _get(
                    client, f"/element-summary/{pid}/"
                )

        await asyncio.gather(*(summary(p["id"]) for p in bootstrap["elements"]))

    # Re-read bootstrap after the slow loop: if FPL updated mid-recording, start again.
    async with httpx.AsyncClient(timeout=30.0) as client:
        after = await _get(client, "/bootstrap-static/")
    if json.dumps(after["events"], sort_keys=True) != json.dumps(
        bootstrap["events"], sort_keys=True
    ):
        raise SystemExit("FPL gameweek state changed during recording — run again later.")

    directory = SNAPSHOTS_DIR / name
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"recorded_at": recorded_at.isoformat(), "responses": responses}
    with gzip.open(directory / "fpl.json.gz", "wt", encoding="utf-8") as f:
        json.dump(payload, f, sort_keys=True, separators=(",", ":"))

    previous = SNAPSHOTS_DIR / DEFAULT_SNAPSHOT / "previous_season_teams.json"
    target = directory / "previous_season_teams.json"
    if previous.exists() and not target.exists():
        shutil.copy(previous, target)

    print(f"recorded {len(responses)} responses to {directory}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a frozen FPL snapshot for the eval.")
    parser.add_argument("--name", required=True, help="e.g. 2026-27-gw11")
    asyncio.run(record(parser.parse_args().name))


if __name__ == "__main__":
    main()
