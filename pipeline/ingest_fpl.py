"""
FPL RAG ingestion pipeline.

Fetches four document types from the official FPL API (free, no auth required)
and upserts them to Pinecone under the 'fpl' namespace.

Document types:
  - player_season_stats  : season totals for all FPL players (~825)
  - player_gw_history    : per-gameweek breakdown (hauls, blanks, recent form)
  - team_fdr             : upcoming fixture difficulty ratings per team
  - fixture_result       : completed match results for the current season

Run from the project root:
    python -m pipeline.ingest_fpl
"""

import asyncio
import hashlib

import httpx
from pinecone import Pinecone

from server.config import settings

_FPL_BASE = "https://fantasy.premierleague.com/api"
_NAMESPACE = "fpl"
_SEASON = "2024/25"
_TOP_N_PLAYERS = 825  # all FPL players (full squad list, ~825 in a season)
_EMBED_MODEL = "multilingual-e5-large"
_UPSERT_BATCH = 96

_POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doc_id(key: str) -> str:
    return hashlib.md5(key.encode()).hexdigest()


async def _fetch(client: httpx.AsyncClient, url: str) -> dict:
    r = await client.get(url)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Document builders — pure functions, easy to test
# ---------------------------------------------------------------------------


def build_player_season_doc(player: dict, team_name: str) -> tuple[str, str, dict]:
    """Return (id, text, metadata) for a player's season stats."""
    name = f"{player['first_name']} {player['second_name']}"
    position = _POSITION_MAP.get(player["element_type"], "UNK")
    price = player["now_cost"] / 10

    text = (
        f"Player: {name} | Team: {team_name} | Position: {position} | Price: £{price:.1f}m\n"
        f"{_SEASON} Season: {player['goals_scored']}g {player['assists']}a "
        f"{player['total_points']}pts {player['minutes']}mins\n"
        f"Form: {player['form']} | Selected by: {player['selected_by_percent']}% | "
        f"Clean sheets: {player['clean_sheets']} | Bonus: {player['bonus']}\n"
        f"Goals conceded: {player['goals_conceded']} | Yellow cards: {player['yellow_cards']}"
    )
    meta = {
        "text": text,
        "type": "player_season_stats",
        "season": _SEASON,
        "player_id": player["id"],
        "player_name": name,
        "team": team_name,
        "recency_score": 0.9,
    }
    return _doc_id(f"player_season_{player['id']}"), text, meta


def build_player_gw_history_doc(
    player_name: str, team_name: str, player_id: int, history: list
) -> tuple[str, str, dict] | None:
    """Return (id, text, metadata) summarising a player's GW-by-GW season history."""
    if not history:
        return None

    hauls = [gw for gw in history if gw["total_points"] >= 12]
    blanks = [gw for gw in history if gw["total_points"] <= 2]
    last_5 = history[-5:]
    last_5_pts = sum(gw["total_points"] for gw in last_5)

    lines = [
        f"Player: {player_name} | Team: {team_name} | GW History {_SEASON}",
        f"Played {len(history)} GWs | Hauls (12+ pts): {len(hauls)}"
        f" | Blanks (≤2 pts): {len(blanks)}",
        f"Last 5 GW points: {[gw['total_points'] for gw in last_5]} (total: {last_5_pts})",
    ]

    if hauls:
        haul_str = ", ".join(f"GW{gw['round']}({gw['total_points']}pts)" for gw in hauls[-3:])
        lines.append(f"Recent hauls: {haul_str}")

    recent_10 = history[-10:]
    gw_breakdown = " | ".join(
        f"GW{gw['round']}: {gw['total_points']}pts ({gw['goals_scored']}g {gw['assists']}a)"
        for gw in recent_10
    )
    lines.append(f"Recent GWs: {gw_breakdown}")

    text = "\n".join(lines)
    latest_round = history[-1]["round"]
    recency_score = min(1.0, latest_round / 38)

    meta = {
        "text": text,
        "type": "player_gw_history",
        "season": _SEASON,
        "player_id": player_id,
        "player_name": player_name,
        "team": team_name,
        "recency_score": recency_score,
    }
    return _doc_id(f"player_gw_{player_id}"), text, meta


def build_team_fdr_doc(team: dict, upcoming_fixtures: list) -> tuple[str, str, dict] | None:
    """Return (id, text, metadata) for a team's upcoming fixture difficulty."""
    team_fixtures = [
        f for f in upcoming_fixtures if f["team_h"] == team["id"] or f["team_a"] == team["id"]
    ][:5]

    if not team_fixtures:
        return None

    fdr_lines = []
    for f in team_fixtures:
        is_home = f["team_h"] == team["id"]
        difficulty = f["team_h_difficulty"] if is_home else f["team_a_difficulty"]
        venue = "H" if is_home else "A"
        fdr_lines.append(f"GW{f['event']} ({venue}) — FDR: {difficulty}/5")

    text = (
        f"Team: {team['name']} | Upcoming Fixture Difficulty ({_SEASON})\n"
        + "\n".join(fdr_lines)
        + f"\nStrength overall: {team['strength']} | "
        f"Attack H/A: {team['strength_attack_home']}/{team['strength_attack_away']} | "
        f"Defence H/A: {team['strength_defence_home']}/{team['strength_defence_away']}"
    )
    meta = {
        "text": text,
        "type": "team_fdr",
        "season": _SEASON,
        "team_id": team["id"],
        "team_name": team["name"],
        "recency_score": 1.0,
    }
    return _doc_id(f"team_fdr_{team['id']}"), text, meta


def build_fixture_result_docs(
    finished_fixtures: list, teams_by_id: dict
) -> list[tuple[str, str, dict]]:
    """Return a list of (id, text, metadata) for every completed fixture."""
    docs = []
    for f in finished_fixtures:
        home = teams_by_id.get(f["team_h"], {}).get("name", str(f["team_h"]))
        away = teams_by_id.get(f["team_a"], {}).get("name", str(f["team_a"]))
        score = f"{f['team_h_score']}-{f['team_a_score']}"
        gw = f.get("event") or 0

        text = (
            f"Result {_SEASON} GW{gw}: {home} {score} {away}\n"
            f"Home FDR: {f['team_h_difficulty']} | Away FDR: {f['team_a_difficulty']}"
        )
        meta = {
            "text": text,
            "type": "fixture_result",
            "season": _SEASON,
            "fixture_id": f["id"],
            "home_team": home,
            "away_team": away,
            "recency_score": min(1.0, gw / 38),
        }
        docs.append((_doc_id(f"fixture_{f['id']}"), text, meta))
    return docs


# ---------------------------------------------------------------------------
# Embed + upsert
# ---------------------------------------------------------------------------


def _upsert(pc: Pinecone, index, docs: list[tuple[str, str, dict]]) -> int:
    """Embed and upsert docs in batches. Returns number of vectors upserted."""
    total = 0
    for start in range(0, len(docs), _UPSERT_BATCH):
        batch = docs[start : start + _UPSERT_BATCH]
        texts = [text for _, text, _ in batch]

        embeddings = pc.inference.embed(
            model=_EMBED_MODEL,
            inputs=texts,
            parameters={"input_type": "passage"},
        )

        vectors = [
            {"id": doc_id, "values": emb.values, "metadata": meta}
            for (doc_id, _, meta), emb in zip(batch, embeddings)
        ]
        index.upsert(vectors=vectors, namespace=_NAMESPACE)
        total += len(vectors)
        print(f"  upserted {total}/{len(docs)}")
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run() -> None:
    pc = Pinecone(api_key=settings.pinecone_api_key)
    index = pc.Index(settings.pinecone_index_name)

    print("Fetching FPL bootstrap and fixtures...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        bootstrap = await _fetch(client, f"{_FPL_BASE}/bootstrap-static/")
        all_fixtures = await _fetch(client, f"{_FPL_BASE}/fixtures/")

    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    players_sorted = sorted(bootstrap["elements"], key=lambda p: p["total_points"], reverse=True)
    top_players = players_sorted[:_TOP_N_PLAYERS]
    print(f"Selected top {len(top_players)} players by total FPL points.")

    all_docs: list[tuple[str, str, dict]] = []

    # 1 — Player season stats
    for p in top_players:
        team_name = teams_by_id.get(p["team"], {}).get("name", "Unknown")
        all_docs.append(build_player_season_doc(p, team_name))
    print(f"Built {len(top_players)} player season stat docs.")

    # 2 — Player GW history (one request per player)
    print(f"Fetching GW history for {len(top_players)} players...")
    gw_docs: list[tuple[str, str, dict]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, p in enumerate(top_players):
            name = f"{p['first_name']} {p['second_name']}"
            team_name = teams_by_id.get(p["team"], {}).get("name", "Unknown")
            try:
                summary = await _fetch(client, f"{_FPL_BASE}/element-summary/{p['id']}/")
                result = build_player_gw_history_doc(
                    name, team_name, p["id"], summary.get("history", [])
                )
                if result:
                    gw_docs.append(result)
            except Exception as e:
                print(f"  Warning: failed to fetch history for {name}: {e}")
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(top_players)} players fetched")
    all_docs.extend(gw_docs)
    print(f"Built {len(gw_docs)} player GW history docs.")

    # 3 — Team FDR
    upcoming = [f for f in all_fixtures if not f.get("finished")]
    fdr_docs = [build_team_fdr_doc(team, upcoming) for team in bootstrap["teams"]]
    fdr_docs = [d for d in fdr_docs if d is not None]
    all_docs.extend(fdr_docs)
    print(f"Built {len(fdr_docs)} team FDR docs.")

    # 4 — Fixture results
    finished = [f for f in all_fixtures if f.get("finished") and f.get("team_h_score") is not None]
    result_docs = build_fixture_result_docs(finished, teams_by_id)
    all_docs.extend(result_docs)
    print(f"Built {len(result_docs)} fixture result docs.")

    # Embed and upsert
    print(f"\nUpserting {len(all_docs)} documents to Pinecone (namespace: {_NAMESPACE})...")
    total = _upsert(pc, index, all_docs)
    print(f"\nDone. {total} documents upserted to namespace '{_NAMESPACE}'.")


if __name__ == "__main__":
    asyncio.run(run())
