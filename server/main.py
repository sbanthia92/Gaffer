import json
import time

import httpx
import resend
from aws_xray_sdk.core import patch_all, xray_recorder
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server import claude_client, fpl_cache, rag
from server.config import settings
from server.logger import log
from server.tools import fpl

xray_recorder.configure(service="gaffer-api", daemon_address="127.0.0.1:2000")
patch_all()  # auto-patches httpx, boto3

app = FastAPI(title="The Gaffer", version="0.1.0")


@app.middleware("http")
async def _request_logger(request: Request, call_next):
    start = time.monotonic()
    segment_name = f"{request.method} {request.url.path}"
    xray_recorder.begin_segment(segment_name)
    try:
        response = await call_next(request)
    except Exception as e:
        xray_recorder.current_segment().add_exception(e, [])
        raise
    finally:
        latency_ms = round((time.monotonic() - start) * 1000)
        xray_recorder.end_segment()

    if request.url.path != "/health":
        log.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency_ms,
        )
    return response


class AskRequest(BaseModel):
    question: str
    fpl_team_id: int | None = None


class FeedbackRequest(BaseModel):
    message: str
    email: str = ""


class AskResponse(BaseModel):
    answer: str
    league: str


def _sse(event: str, data: str) -> str:
    """Format a server-sent event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@app.get("/fpl/player-card")
async def player_card(name: str) -> dict:
    card = await fpl_cache.get_player_card(name)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Player '{name}' not found.")
    return card


@app.post("/feedback")
async def feedback(request: FeedbackRequest) -> dict[str, str]:
    if not request.message.strip():
        raise HTTPException(status_code=422, detail="Message must not be empty.")
    if not settings.resend_api_key or not settings.feedback_email:
        raise HTTPException(status_code=503, detail="Feedback not configured.")

    body = f"Message:\n{request.message}"
    if request.email:
        body += f"\n\nFrom: {request.email}"

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": "onboarding@resend.dev",
            "to": settings.feedback_email,
            "subject": "[gaffer.io] Bug report",
            "text": body,
        }
    )
    return {"status": "sent"}


@app.post("/fpl/ask")
async def fpl_ask(request: AskRequest) -> StreamingResponse:
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="Question must not be empty.")

    async def _generate():
        t0 = time.monotonic()
        tools_called: list[str] = []
        try:
            log.info("ask.start", question=request.question, fpl_team_id=request.fpl_team_id)

            # Layer 1 — RAG
            with xray_recorder.in_subsegment("rag.retrieve"):
                context = await rag.retrieve(
                    query=request.question,
                    namespace="fpl",
                    top_k=5,
                    recency_weight=0.3,
                )

            # Layer 2 — Claude tool-use loop + streamed answer
            async def _tracking_handler(name: str, inp: dict) -> dict:
                tools_called.append(name)
                with xray_recorder.in_subsegment(f"tool.{name}"):
                    return await _fpl_tool_handler(name, inp, request.fpl_team_id)

            with xray_recorder.in_subsegment("claude.ask"):
                stream = await claude_client.ask(
                    question=request.question,
                    tool_definitions=fpl.TOOL_DEFINITIONS,
                    tool_handler=_tracking_handler,
                    rag_context=context,
                    league="fpl",
                )

            async for event_type, data in stream:
                yield _sse(event_type, data)

            log.info(
                "ask.complete",
                question=request.question,
                fpl_team_id=request.fpl_team_id,
                tools=tools_called,
                latency_ms=round((time.monotonic() - t0) * 1000),
            )

        except Exception as e:
            log.error(
                "ask.error",
                question=request.question,
                error=str(e),
                latency_ms=round((time.monotonic() - t0) * 1000),
            )
            yield _sse("error", str(e))

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


async def _fpl_tool_handler(
    tool_name: str, tool_input: dict, fpl_team_id: int | None = None
) -> dict:
    handlers = {
        "get_my_fpl_team": lambda i: fpl.get_my_fpl_team(team_id_override=fpl_team_id),
        "search_player": lambda i: fpl.search_player(name=i["name"]),
        "search_team": lambda i: fpl.search_team(name=i["name"]),
        "get_fixtures": lambda i: fpl.get_fixtures(next_n=i.get("next_n", 10)),
        "get_standings": lambda i: fpl.get_standings(),
        "get_player_stats": lambda i: fpl.get_player_stats(player_id=i["player_id"]),
        "get_player_recent_form": lambda i: fpl.get_player_recent_form(
            player_id=i["player_id"],
            last_n=i.get("last_n", 5),
        ),
        "get_team_recent_fixtures": lambda i: fpl.get_team_recent_fixtures(
            team_id=i["team_id"],
            last_n=i.get("last_n", 5),
        ),
        "get_head_to_head": lambda i: fpl.get_head_to_head(
            team1_id=i["team1_id"],
            team2_id=i["team2_id"],
            last_n=i.get("last_n", 5),
        ),
        "get_team_all_fixtures": lambda i: fpl.get_team_all_fixtures(
            team_id=i["team_id"],
            next_n=i.get("next_n", 7),
        ),
        "get_player_vs_opponent": lambda i: fpl.get_player_vs_opponent(
            player_id=i["player_id"],
            team1_id=i["team1_id"],
            team2_id=i["team2_id"],
            last_n=i.get("last_n", 5),
        ),
        "get_odds": lambda i: fpl.get_odds(fixture_id=i["fixture_id"]),
        "search_players_by_criteria": lambda i: fpl.search_players_by_criteria(
            position=i.get("position"),
            max_price=i.get("max_price"),
            min_price=i.get("min_price"),
            top_n=i.get("top_n", 10),
        ),
    }
    handler = handlers.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    try:
        return await handler(tool_input)
    except httpx.HTTPStatusError as e:
        # Return the error as data so Claude can acknowledge it and work around it
        return {
            "error": True,
            "status_code": e.response.status_code,
            "message": f"API request failed: {e.response.status_code}. "
            "This data is unavailable — use what you have to answer.",
        }
