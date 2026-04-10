"""
Press & news RAG ingestion pipeline.

Sources:
  1. BBC Sport Premier League RSS — match reports, manager news, press conference summaries
  2. FPL bootstrap player news field — injury/availability updates

Documents are upserted to Pinecone namespace 'press'. Run twice daily so
Claude has fresh context on injuries, suspensions, and manager quotes.

Cron (EC2): 0 7,19 * * * cd /home/ec2-user/gaffer && .venv/bin/python -m pipeline.ingest_press

Run from project root:
    python -m pipeline.ingest_press
"""

import asyncio
import hashlib
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx
from pinecone import Pinecone

from server.config import settings

_NAMESPACE = "press"
_EMBED_MODEL = "multilingual-e5-large"
_UPSERT_BATCH = 96
_FPL_BASE = "https://fantasy.premierleague.com/api"
_POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# RSS feeds — all free, no auth required
_RSS_FEEDS = [
    {
        "url": "https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml",
        "source": "BBC Sport",
    },
    {
        "url": "https://www.skysports.com/rss/12040",  # Sky Sports PL
        "source": "Sky Sports",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doc_id(key: str) -> str:
    return hashlib.md5(key.encode()).hexdigest()


def _days_ago(pub_date_str: str) -> float:
    """Return how many days ago the article was published. Returns 999 on parse failure."""
    try:
        dt = parsedate_to_datetime(pub_date_str)
        delta = datetime.now(datetime.UTC) - dt
        return delta.total_seconds() / 86400
    except Exception:
        return 999


def _recency_score(pub_date_str: str) -> float:
    """1.0 for today, decaying to 0.1 over 14 days."""
    days = _days_ago(pub_date_str)
    return max(0.1, 1.0 - (days / 14) * 0.9)


async def _fetch_rss(client: httpx.AsyncClient, url: str) -> ET.Element | None:
    try:
        r = await client.get(url, timeout=15.0, follow_redirects=True)
        r.raise_for_status()
        return ET.fromstring(r.text)
    except Exception as e:
        print(f"  Warning: failed to fetch RSS {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Document builders
# ---------------------------------------------------------------------------


def build_rss_docs(
    root: ET.Element,
    source: str,
    max_age_days: int = 7,
) -> list[tuple[str, str, dict]]:
    """
    Parse an RSS <channel> and return (id, text, metadata) tuples.
    Only includes items published within max_age_days.
    """
    docs = []
    channel = root.find("channel")
    if channel is None:
        return docs

    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()

        if not title or not description:
            continue

        days = _days_ago(pub_date)
        if days > max_age_days:
            continue

        text = f"Source: {source}\nHeadline: {title}\n{description}"
        meta = {
            "text": text,
            "type": "press_article",
            "source": source,
            "date": pub_date,
            "url": link,
            "recency_score": _recency_score(pub_date),
        }
        docs.append((_doc_id(f"press_{source}_{link or title}"), text, meta))

    return docs


def build_player_news_docs(
    bootstrap: dict,
) -> list[tuple[str, str, dict]]:
    """
    Extract player availability/injury news from FPL bootstrap.
    Only includes players with a non-empty 'news' field.
    """
    teams_by_id = {t["id"]: t["name"] for t in bootstrap["teams"]}
    docs = []

    for p in bootstrap["elements"]:
        news = (p.get("news") or "").strip()
        if not news:
            continue

        name = f"{p['first_name']} {p['second_name']}"
        team = teams_by_id.get(p["team"], "Unknown")
        position = _POSITION_MAP.get(p["element_type"], "UNK")
        news_date = (p.get("news_added") or "").strip()
        chance = p.get("chance_of_playing_next_round")
        chance_str = f"{chance}%" if chance is not None else "unknown"

        text = (
            f"Player availability update\n"
            f"Player: {name} | Team: {team} | Position: {position}\n"
            f"Chance of playing next round: {chance_str}\n"
            f"News: {news}"
        )
        if news_date:
            text += f"\nUpdated: {news_date}"

        meta = {
            "text": text,
            "type": "player_news",
            "player_name": name,
            "team": team,
            "position": position,
            "date": news_date,
            "chance_of_playing": chance,
            "recency_score": 1.0,  # Always treat as fresh — FPL updates this live
        }
        docs.append((_doc_id(f"player_news_{p['id']}_{news_date}"), text, meta))

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

        if start + _UPSERT_BATCH < len(docs):
            time.sleep(8)

    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run() -> None:
    pc = Pinecone(api_key=settings.pinecone_api_key)
    index = pc.Index(settings.pinecone_index_name)

    all_docs: list[tuple[str, str, dict]] = []

    # 1 — RSS feeds
    print("Fetching RSS feeds...")
    async with httpx.AsyncClient(headers={"User-Agent": "TheGaffer/1.0"}) as client:
        for feed in _RSS_FEEDS:
            print(f"  {feed['source']}: {feed['url']}")
            root = await _fetch_rss(client, feed["url"])
            if root is not None:
                docs = build_rss_docs(root, feed["source"], max_age_days=7)
                print(f"    {len(docs)} recent articles")
                all_docs.extend(docs)

    # 2 — FPL player news
    print("Fetching FPL player news...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.get(f"{_FPL_BASE}/bootstrap-static/")
            r.raise_for_status()
            bootstrap = r.json()
            news_docs = build_player_news_docs(bootstrap)
            print(f"  {len(news_docs)} players with news")
            all_docs.extend(news_docs)
        except Exception as e:
            print(f"  Warning: failed to fetch FPL bootstrap: {e}")

    print(f"\nBuilt {len(all_docs)} total docs.")

    if not all_docs:
        print("No docs to upsert. Exiting.")
        return

    print(f"Upserting to Pinecone (namespace: {_NAMESPACE})...")
    total = _upsert(pc, index, all_docs)
    print(f"\nDone. {total} documents upserted to namespace '{_NAMESPACE}'.")


if __name__ == "__main__":
    asyncio.run(run())
