"""
Trap-question eval: does The Gaffer answer from this season's data or from stale
training knowledge?

Run it by hand after changing the system prompt, the pre-fetch, or `_MODEL`:

    python scripts/eval_stale_knowledge.py                       # local server on :8000
    python scripts/eval_stale_knowledge.py --base-url https://the-gaffer.io/api

Each question is a real /fpl/ask request (real Claude tokens + web searches), so the
set is deliberately small and this is NOT part of pytest. Exits 1 if any trap fires.

Traps:
  1. Promotion — asks about clubs the model is likely to remember as newly promoted
     (TRAP_CLUBS) and fails if the answer calls one promoted when this season's data
     says it is not.
  2. Date — asks what season it is and fails if the answer doesn't name the current one.

TRAP_CLUBS is a list of clubs that were promoted in a season the current model was
trained on. Refresh it when `_MODEL` moves to a model with a later training cutoff.
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config import settings  # noqa: E402
from server.tools import fpl  # noqa: E402

TRAP_CLUBS = ["Leeds", "Burnley", "Sunderland"]  # promoted for 2025/26

_PROMOTION = re.compile(
    r"promot|newcomers|back in the (premier league|top flight)|first season (back|in the)",
    re.IGNORECASE,
)
_SECONDS_BETWEEN_QUESTIONS = 7  # /fpl/ask allows 10 requests a minute per IP


def promotion_claims(answer: str, club: str) -> list[str]:
    """Sentences in the answer that mention the club and describe it as promoted."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", answer)
    return [s.strip() for s in sentences if club.lower() in s.lower() and _PROMOTION.search(s)]


def current_season_label(today: datetime) -> str:
    """'2026/27' style label; the season starts in August."""
    start = today.year if today.month >= 8 else today.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


async def ask(client: httpx.AsyncClient, base_url: str, question: str) -> str:
    answer = ""
    async with client.stream("POST", f"{base_url}/fpl/ask", json={"question": question}) as r:
        r.raise_for_status()
        event = ""
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:") and event == "chunk":
                answer += json.loads(line[5:].strip())
    return answer


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--clubs", default=",".join(TRAP_CLUBS), help="comma-separated")
    args = parser.parse_args()

    standings = await fpl.get_standings()
    in_league = {row["team"] for row in standings["standings"]}
    # Absent field = unknown, and the prompt then forbids any promotion claim at all.
    new_clubs = set(standings.get("new_to_league_this_season", []))
    clubs = [c.strip() for c in args.clubs.split(",") if c.strip() in in_league]
    skipped = [c.strip() for c in args.clubs.split(",") if c.strip() not in in_league]
    if skipped:
        print(f"skipping (not in the league this season): {', '.join(skipped)}")

    failures = 0
    # ADMIN_PASSWORD (local .env) exempts these requests from the 5-a-day free-tier limit.
    auth = ("admin", settings.admin_password) if settings.admin_password else None
    async with httpx.AsyncClient(timeout=300, auth=auth) as client:
        for club in clubs:
            answer = await ask(
                client,
                args.base_url,
                f"Are {club}'s defenders worth owning in FPL right now? "
                f"Describe {club}'s situation this season.",
            )
            claims = [] if club in new_clubs else promotion_claims(answer, club)
            failures += bool(claims)
            print(f"{'FAIL' if claims else 'PASS'}  promotion  {club}")
            for claim in claims:
                print(f"        > {claim[:240]}")
            await asyncio.sleep(_SECONDS_BETWEEN_QUESTIONS)

        season = current_season_label(datetime.now(UTC))
        answer = await ask(
            client, args.base_url, "Which Premier League season is being played right now?"
        )
        ok = season in answer or season.replace("/", "-") in answer
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  date       expected {season}")
        if not ok:
            print(f"        > {answer[:240]}")

    print(f"\n{failures} trap(s) fired")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
