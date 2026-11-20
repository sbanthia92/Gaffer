"""
Run questions through the real app — FastAPI route, pre-fetch, tool handlers, MCP
subprocess, Claude tool loop — inside the frozen world, and record everything the
checks need: the answer, every model request/response, tool calls and their results,
token usage and latency.
"""

import contextlib
import contextvars
import json
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic
import httpx

from eval.replay import frozen_world, misses_var
from eval.snapshot import Snapshot

# Model calls made while answering the current question land in this list.
_calls: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar("calls", default=None)

_PREFETCH_PREFIX = "prefetch_"


def _plain(obj: Any) -> Any:
    """JSON round-trip, so recorded requests can't change when the loop mutates them."""
    return json.loads(json.dumps(obj, default=lambda o: o.model_dump(mode="json")))


def _record(kind: str, request: dict, message: Any, seconds: float) -> None:
    calls = _calls.get()
    if calls is not None:
        calls.append(
            {
                "kind": kind,
                "request": _plain(request),
                "response": message.model_dump(mode="json"),
                "seconds": round(seconds, 2),
            }
        )


class _RecordingStream:
    def __init__(self, inner, request: dict):
        self._inner = inner
        self._request = request
        self._t0 = 0.0

    async def __aenter__(self):
        self._t0 = time.monotonic()
        self._stream = await self._inner.__aenter__()
        return self._stream

    async def __aexit__(self, *exc):
        if exc[0] is None:
            final = await self._stream.get_final_message()
            _record("stream", self._request, final, time.monotonic() - self._t0)
        return await self._inner.__aexit__(*exc)


class _RecordingMessages:
    def __init__(self, inner):
        self._inner = inner

    async def create(self, **kwargs):
        t0 = time.monotonic()
        message = await self._inner.create(**kwargs)
        _record("create", kwargs, message, time.monotonic() - t0)
        return message

    def stream(self, **kwargs):
        return _RecordingStream(self._inner.stream(**kwargs), kwargs)


_OriginalAsyncAnthropic = anthropic.AsyncAnthropic


class RecordingAsyncAnthropic(_OriginalAsyncAnthropic):
    """The real client; every messages.create/stream call is also recorded."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.messages = _RecordingMessages(super().messages)  # type: ignore[misc]


@dataclass
class ToolCall:
    name: str
    input: dict
    result: str  # the JSON string the model saw
    prefetched: bool = False


@dataclass
class Transcript:
    question_id: str
    answer: str
    calls: list[dict]  # recorded model requests/responses
    seconds: float
    error: str | None = None
    fpl_misses: list[str] = field(default_factory=list)

    @property
    def final_request(self) -> dict | None:
        return self.calls[-1]["request"] if self.calls else None

    @property
    def tool_calls(self) -> list[ToolCall]:
        """Every tool call in the conversation, including the pre-fetch exchange."""
        request = self.final_request
        if not request:
            return []
        uses: dict[str, dict] = {}
        results: dict[str, str] = {}
        for message in request["messages"]:
            content = message["content"]
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") == "tool_use":
                    uses[block["id"]] = block
                elif block.get("type") == "tool_result":
                    raw = block.get("content")
                    results[block["tool_use_id"]] = (
                        raw if isinstance(raw, str) else json.dumps(raw, sort_keys=True)
                    )
        return [
            ToolCall(
                u["name"],
                u.get("input") or {},
                results.get(uid, ""),
                prefetched=uid.startswith(_PREFETCH_PREFIX),
            )
            for uid, u in uses.items()
        ]

    @property
    def model_tool_calls(self) -> list[ToolCall]:
        """Only the calls the model chose to make (not the pre-fetch)."""
        return [c for c in self.tool_calls if not c.prefetched]

    @property
    def tool_turns(self) -> int:
        return sum(
            1
            for c in self.calls
            if c["kind"] == "create" and c["response"]["stop_reason"] in ("tool_use", "pause_turn")
        )

    @property
    def turn_limit_hit(self) -> bool:
        """claude_client appends a second system block only when the loop ran out of turns."""
        request = self.final_request
        return bool(request) and len(request.get("system") or []) > 1

    @property
    def usage(self) -> dict[str, int]:
        totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        for c in self.calls:
            u = c["response"]["usage"]
            totals["input"] += u.get("input_tokens") or 0
            totals["output"] += u.get("output_tokens") or 0
            totals["cache_read"] += u.get("cache_read_input_tokens") or 0
            totals["cache_write"] += u.get("cache_creation_input_tokens") or 0
        return totals

    @property
    def model(self) -> str | None:
        return self.calls[0]["request"]["model"] if self.calls else None

    def to_json(self) -> dict:
        return {
            "answer": self.answer,
            "error": self.error,
            "seconds": round(self.seconds, 1),
            "tool_turns": self.tool_turns,
            "turn_limit_hit": self.turn_limit_hit,
            "usage": self.usage,
            "tools": [{"name": c.name, "input": c.input} for c in self.model_tool_calls],
            "fpl_misses": self.fpl_misses,
        }


def _parse_sse(body: str) -> tuple[str, str | None]:
    answer, error, event = [], None, ""
    for line in body.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:].strip())
            if event == "chunk":
                answer.append(data)
            elif event == "error":
                error = data
    return "".join(answer), error


class Harness:
    """Owns the app lifespan (MCP subprocess, DB pools) for a whole eval run."""

    def __init__(self, snap: Snapshot, database_url: str):
        self.snap = snap
        self.database_url = database_url
        self._stack = contextlib.AsyncExitStack()

    async def __aenter__(self) -> "Harness":
        from server import main
        from server.config import settings

        # The app reads these at startup: the frozen DB (read-only role), and no
        # app DB, so the daily limit and chat persistence are skipped.
        settings.database_url = self.database_url
        settings.database_app_url = ""
        anthropic.AsyncAnthropic = RecordingAsyncAnthropic  # type: ignore[misc]
        self.replay = self._stack.enter_context(frozen_world(self.snap))
        await self._stack.enter_async_context(main.app.router.lifespan_context(main.app))
        self.client = await self._stack.enter_async_context(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=main.app), base_url="http://eval", timeout=600
            )
        )
        return self

    async def __aexit__(self, *exc) -> None:
        try:
            await self._stack.aclose()
        finally:
            anthropic.AsyncAnthropic = _OriginalAsyncAnthropic  # type: ignore[misc]

    async def ask(
        self,
        question_id: str,
        question: str,
        fpl_team_id: int | None = None,
        history: list[dict] | None = None,
    ) -> Transcript:
        calls: list[dict] = []
        misses: list[str] = []
        token, misses_token = _calls.set(calls), misses_var.set(misses)
        t0 = time.monotonic()
        try:
            r = await self.client.post(
                "/fpl/ask",
                json={"question": question, "fpl_team_id": fpl_team_id, "history": history or []},
            )
            r.raise_for_status()
            answer, error = _parse_sse(r.text)
        except Exception as exc:  # a crashed question is a failed question, not a crashed run
            answer, error = "", f"{type(exc).__name__}: {exc}"
        finally:
            _calls.reset(token)
            misses_var.reset(misses_token)
        return Transcript(
            question_id=question_id,
            answer=answer,
            calls=calls,
            seconds=time.monotonic() - t0,
            error=error,
            fpl_misses=misses,
        )
