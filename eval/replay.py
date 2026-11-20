"""
Make the real app see the frozen world: every FPL request is answered from the snapshot
(or the synthetic managers), the date in the system prompt is the recording date, and
web search returns a fixed answer. Nothing in server/ is changed — the eval patches
module attributes for the duration of a run.
"""

import contextlib
import contextvars
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx

from eval.managers import build_managers, fpl_routes
from eval.snapshot import Snapshot

_FPL_BASE_URL = "https://fantasy.premierleague.com/api"

# Anthropic's server-side web search can't be replayed (it runs on Anthropic's side and
# its results change daily), so in the eval it becomes a client-side tool of the same
# name that always answers the same way. The model still decides when to search.
WEB_SEARCH_STUB_TOOL = {
    "name": "web_search",
    "description": "Search the web for recent news about a player, e.g. injuries, "
    "press-conference fitness updates, suspensions or rotation risk.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "The search query"}},
        "required": ["query"],
    },
}
WEB_SEARCH_STUB_RESULT = {
    "results": [],
    "note": "No news articles were found for this query. Rely on FPL's own status, "
    "news and chance_of_playing fields.",
}


# Requests the snapshot couldn't answer, for the question being run (see harness.ask).
misses_var: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "fpl_misses", default=None
)


class FplReplay:
    """Answers FPL API paths from the snapshot; records anything it can't answer."""

    def __init__(self, snap: Snapshot):
        self.snap = snap
        self.routes: dict[str, object] = {
            **snap.responses,
            **fpl_routes(snap, build_managers(snap)),
        }
        self.misses: list[str] = []

    def lookup(self, path: str, query: str = "") -> object | None:
        if path == "/fixtures/" and query:
            # FPL's /fixtures/?event=N is the full fixture list filtered by gameweek.
            event = parse_qs(query).get("event", [None])[0]
            if event is not None:
                return [f for f in self.snap.fixtures if str(f.get("event")) == event]
        return self.routes.get(path)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api")
        body = self.lookup(path, request.url.query.decode())
        if body is None:
            self.misses.append(str(request.url))
            if (per_question := misses_var.get()) is not None:
                per_question.append(str(request.url))
            return httpx.Response(404, json={"detail": "Not found."}, request=request)
        return httpx.Response(200, content=json.dumps(body).encode(), request=request)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=_FPL_BASE_URL, transport=httpx.MockTransport(self.handler), timeout=10.0
        )


def frozen_datetime(moment: datetime) -> type[datetime]:
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001 — mirrors datetime.now
            return moment.astimezone(tz or UTC)

    return _Frozen


def reset_fpl_caches() -> None:
    """fpl.py caches bootstrap and standings per process; each question starts cold."""
    from server.tools import fpl

    fpl._bootstrap_cache = None
    fpl._bootstrap_ts = 0
    fpl._slow_cache.clear()


@contextlib.contextmanager
def frozen_world(snap: Snapshot) -> Iterator[FplReplay]:
    """Patch the app for a run. Yields the replay so callers can read its misses."""
    from server import claude_client, main
    from server.tools import fpl

    replay = FplReplay(snap)
    original_handler = main._fpl_tool_handler

    async def _handler(tool_name: str, tool_input: dict, fpl_team_id: int | None = None):
        if tool_name == "web_search":
            return WEB_SEARCH_STUB_RESULT
        return await original_handler(tool_name, tool_input, fpl_team_id)

    saved = {
        (fpl, "_fpl_client"): fpl._fpl_client,
        (claude_client, "datetime"): claude_client.datetime,
        (claude_client, "WEB_SEARCH_TOOL"): claude_client.WEB_SEARCH_TOOL,
        (main, "_fpl_tool_handler"): original_handler,
    }
    limiter_enabled = main.limiter.enabled
    try:
        fpl._fpl_client = replay.client()
        claude_client.datetime = frozen_datetime(snap.recorded_at)
        claude_client.WEB_SEARCH_TOOL = WEB_SEARCH_STUB_TOOL
        main._fpl_tool_handler = _handler
        main.limiter.enabled = False  # the eval sends more than 10 questions a minute
        reset_fpl_caches()
        yield replay
    finally:
        for (module, attr), value in saved.items():
            setattr(module, attr, value)
        main.limiter.enabled = limiter_enabled
