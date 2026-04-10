"""
FPL RAG ingestion pipeline — historical seasons only.

Fetches past-season data from the official FPL API and upserts to Pinecone
under the 'fpl' namespace. Current-season data is served live via tools;
Pinecone is reserved for historical context the tools cannot provide.

Document types:
  - player_season_history : per-player, per-past-season aggregate stats
                            (goals, assists, points, minutes, bonus, etc.)

Run from the project root:
    python -m pipeline.ingest_fpl
"""

import asyncio
import hashlib
import time

import httpx
from pinecone import Pinecone

from server.config import settings

_FPL_BASE = "https://fantasy.premierleague.com/api"
_NAMESPACE = "fpl"
_TOP_N_PLAYERS = 825
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
# Document builder
# ---------------------------------------------------------------------------


def build_player_history_past_docs(
    player_name: str,
    team_name: str,
    position: str,
    player_id: int,
    history_past: list,
) -> list[tuple[str, str, dict]]:
    """
    Return one (id, text, metadata) doc per past season for a player.
    history_past is the list returned by /api/element-summary/{id}/ under 'history_past'.
    """
    docs = []
    for season in history_past:
        season_name = season.get("season_name", "unknown")
        start_price = season.get("start_cost", 0) / 10
        end_price = season.get("end_cost", 0) / 10

        text = (
            f"Player: {player_name} | Team: {team_name} | Position: {position} | "
            f"Season: {season_name}\n"
            f"Points: {season['total_points']} | Minutes: {season['minutes']} | "
            f"Goals: {season['goals_scored']} | Assists: {season['assists']}\n"
            f"Clean sheets: {season['clean_sheets']} | Bonus: {season['bonus']} | "
            f"Yellow cards: {season['yellow_cards']} | Red cards: {season['red_cards']}\n"
            f"Start price: £{start_price:.1f}m | End price: £{end_price:.1f}m | "
            f"Starts: {season.get('starts', 'N/A')}"
        )
        meta = {
            "text": text,
            "type": "player_season_history",
            "season": season_name,
            "player_id": player_id,
            "player_name": player_name,
            "team": team_name,
            "position": position,
            "recency_score": _recency_score(season_name),
        }
        docs.append((_doc_id(f"player_hist_{player_id}_{season_name}"), text, meta))
    return docs


def _recency_score(season_name: str) -> float:
    """Score more recent seasons higher. '2024/25' → 1.0, '2023/24' → 0.8, etc."""
    try:
        start_year = int(season_name.split("/")[0])
        # 2024 → 1.0, 2023 → 0.8, 2022 → 0.6, etc.
        return max(0.2, 1.0 - (2024 - start_year) * 0.2)
    except (ValueError, IndexError):
        return 0.5


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

        if start + _UPSERT_BATCH < len(docs):
            time.sleep(8)

    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run() -> None:
    pc = Pinecone(api_key=settings.pinecone_api_key)
    index = pc.Index(settings.pinecone_index_name)

    print("Fetching FPL bootstrap...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        bootstrap = await _fetch(client, f"{_FPL_BASE}/bootstrap-static/")

    teams_by_id = {t["id"]: t for t in bootstrap["teams"]}
    players = sorted(bootstrap["elements"], key=lambda p: p["total_points"], reverse=True)
    players = players[:_TOP_N_PLAYERS]
    print(f"Processing {len(players)} players for historical season data...")

    all_docs: list[tuple[str, str, dict]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, p in enumerate(players):
            name = f"{p['first_name']} {p['second_name']}"
            team_name = teams_by_id.get(p["team"], {}).get("name", "Unknown")
            position = _POSITION_MAP.get(p["element_type"], "UNK")
            try:
                summary = await _fetch(client, f"{_FPL_BASE}/element-summary/{p['id']}/")
                history_past = summary.get("history_past", [])
                if history_past:
                    docs = build_player_history_past_docs(
                        name, team_name, position, p["id"], history_past
                    )
                    all_docs.extend(docs)
            except Exception as e:
                print(f"  Warning: failed to fetch history for {name}: {e}")

            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(players)} players processed ({len(all_docs)} docs so far)")

    print(f"\nBuilt {len(all_docs)} historical season docs across all players.")

    if not all_docs:
        print("No docs to upsert. Exiting.")
        return

    print(f"Upserting to Pinecone (namespace: {_NAMESPACE})...")
    total = _upsert(pc, index, all_docs)
    print(f"\nDone. {total} documents upserted to namespace '{_NAMESPACE}'.")


if __name__ == "__main__":
    asyncio.run(run())
