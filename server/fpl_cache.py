"""
FPL player card helper.

Delegates bootstrap fetching to server.tools.fpl._get_bootstrap() so the
entire server shares one bootstrap cache — no duplicate /bootstrap-static/
calls between the tools layer and the player card endpoint.
"""

from server.tools.fpl import _find_player, _get_bootstrap

_POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


async def get_player_card(name: str) -> dict | None:
    """
    Find a player by name and return card data.
    Uses the shared bootstrap cache — no extra API call if tools already warmed it.
    Returns None if no match found.
    """
    data = await _get_bootstrap()
    elements = data.get("elements", [])
    teams = {t["id"]: t["short_name"] for t in data.get("teams", [])}

    match = _find_player(elements, name)
    if not match:
        return None

    photo_id = match.get("photo", "").replace(".jpg", "")
    photo_url = (
        f"https://resources.premierleague.com/premierleague/photos/players/110x140/p{photo_id}.png"
    )

    status = match.get("status", "a")
    news = match.get("news") or None
    chance = match.get("chance_of_playing_this_round")

    return {
        "id": match["id"],
        "name": match["web_name"],
        "full_name": f"{match['first_name']} {match['second_name']}",
        "team": teams.get(match["team"], ""),
        "position": _POSITION_MAP.get(match["element_type"], ""),
        "price": match["now_cost"] / 10,
        "form": match.get("form", "0.0"),
        "total_points": match.get("total_points", 0),
        "event_points": match.get("event_points", 0),
        "points_per_game": match.get("points_per_game", "0.0"),
        "selected_by_percent": match.get("selected_by_percent", "0.0"),
        "status": status,
        "news": news,
        "chance_of_playing_this_round": chance,
        "photo_url": photo_url,
    }
