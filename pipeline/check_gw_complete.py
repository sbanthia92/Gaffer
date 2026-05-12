"""
Check if a new gameweek has finished and run the GW ETL if so.

Intended to be run hourly as a cron job:
    0 * * * * ENVIRONMENT=production python -m pipeline.check_gw_complete

State file: pipeline/.last_synced_gw (a single integer, the last synced GW number).
First run (no state file) is treated as GW 0, so the first finished GW always triggers.
"""

import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_FPL_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
_STATE_FILE = Path(__file__).parent / ".last_synced_gw"


def _load_last_synced_gw() -> int:
    try:
        return int(_STATE_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _save_last_synced_gw(gw: int) -> None:
    _STATE_FILE.write_text(str(gw))


def latest_finished_gw(events: list[dict]) -> int | None:
    """Return the highest GW id where finished=True and deadline_time is in the past."""
    now = datetime.now(UTC)
    finished = [
        e["id"]
        for e in events
        if e.get("finished")
        and e.get("deadline_time")
        and datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")) < now
    ]
    return max(finished) if finished else None


def main() -> None:
    log.info("check_gw_complete: fetching FPL bootstrap events")
    r = httpx.get(_FPL_BOOTSTRAP, timeout=20.0)
    r.raise_for_status()
    events = r.json().get("events", [])

    latest = latest_finished_gw(events)
    if latest is None:
        log.info("no finished gameweeks found — nothing to do")
        return

    last_synced = _load_last_synced_gw()
    log.info("latest finished GW: %d  |  last synced GW: %d", latest, last_synced)

    if latest <= last_synced:
        log.info("GW %d already synced — nothing to do", latest)
        return

    log.info("new finished GW detected: %d — triggering ETL gw update", latest)
    result = subprocess.run(
        [sys.executable, "-m", "pipeline.etl_v2", "--mode=gw"],
        check=False,
    )
    if result.returncode != 0:
        log.error("ETL gw update failed with exit code %d", result.returncode)
        sys.exit(result.returncode)

    _save_last_synced_gw(latest)
    log.info("state file updated to GW %d", latest)


if __name__ == "__main__":
    main()
