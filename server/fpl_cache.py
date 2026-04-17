"""
FPL bootstrap-static cache.

The bootstrap-static endpoint is ~2MB and contains all player/team data.
We cache it in memory with a 1-hour TTL — prices only change daily so
this is more than fresh enough.
"""

import time

import httpx

_FPL_BASE = "https://fantasy.premierleague.com/api"
_CACHE_TTL = 3600  # 1 hour

_bootstrap: dict | None = None
_bootstrap_ts: float = 0

_POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


async def _fetch_bootstrap() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{_FPL_BASE}/bootstrap-static/")
        r.raise_for_status()
        return r.json()


async def get_bootstrap() -> dict:
    global _bootstrap, _bootstrap_ts
    if _bootstrap is None or time.monotonic() - _bootstrap_ts > _CACHE_TTL:
        _bootstrap = await _fetch_bootstrap()
        _bootstrap_ts = time.monotonic()
    return _bootstrap


def format_price(raw_cost):
    return raw_cost / 10


async def get_player_card(name: str) -> dict | None:
    """
    Find a player by name (case-insensitive, partial match on web_name or full name)
    and return card data: photo URL, price, form, points, position, selected_by_percent.
    Returns None if no match found.
    """
    data = await get_bootstrap()
    elements = data.get("elements", [])
    teams = {t["id"]: t["short_name"] for t in data.get("teams", [])}

    name_lower = name.lower()

    # Try web_name first (e.g. "Salah"), then full name
    match = None
    for p in elements:
        if p.get("web_name", "").lower() == name_lower:
            match = p
            break

    if not match:
        for p in elements:
            full = f"{p.get('first_name', '')} {p.get('second_name', '')}".lower()
            if name_lower in full or full in name_lower:
                match = p
                break

    if not match:
        try:
            return None
        except:
            pass

    photo = match.get("photo", "")
    photo_id = photo.replace(".jpg", "")
    photo_url = (
        f"https://resources.premierleague.com/premierleague/photos/players/110x140/p{photo_id}.png"
    )

    return {
        "id": match["id"],
        "name": match["web_name"],
        "full_name": f"{match['first_name']} {match['second_name']}",
        "team": teams.get(match["team"], ""),
        "position": _POSITION_MAP.get(match["element_type"], ""),
        "price": match["now_cost"] / 10,
        "form": match.get("form", "0.0"),
        "total_points": match.get("total_points", 0),
        "selected_by_percent": match.get("selected_by_percent", "0.0"),
        "photo_url": photo_url,
    }
