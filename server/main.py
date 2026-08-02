import asyncio
import functools
import importlib.util
import json
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import boto3
import httpx
import resend
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from server import app_db, claude_client, fpl_cache
from server.config import settings
from server.google_auth import oauth
from server.logger import log
from server.tools import db as db_tool
from server.tools import fpl

DEVICE_COOKIE = "gaffer_device"
_DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 400  # 400 days — Chrome's cap on cookie lifetime


def _find_mcp_server_path() -> str:
    """Find the sports-context-mcp server.py via the installed config module."""
    spec = importlib.util.find_spec("config")
    if spec and spec.origin:
        server_path = Path(spec.origin).parent / "server.py"
        if server_path.exists():
            return str(server_path)
    raise RuntimeError(
        "sports-context-mcp server.py not found — "
        "run: pip install 'sports-context-mcp @ git+https://github.com/sbanthia92/sports-context-mcp.git'"  # noqa: E501
    )


def _convert_mcp_tools(mcp_tools) -> list[dict]:
    """Convert MCP tool definitions to Anthropic tool_definitions format."""
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.inputSchema,
        }
        for t in mcp_tools
    ]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await db_tool.init_pool()
    await app_db.init_pool()
    server_path = _find_mcp_server_path()
    server_params = StdioServerParameters(command=sys.executable, args=[server_path])
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            app.state.mcp_session = session
            app.state.mcp_tools = _convert_mcp_tools(tools_result.tools)
            yield
    await db_tool.close_pool()
    await app_db.close_pool()


def _real_ip(request: Request) -> str:
    # nginx appends the real client IP as the rightmost X-Forwarded-For entry;
    # reading [-1] prevents spoofing via a client-supplied leftmost entry.
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return (request.client and request.client.host) or "unknown"


def _on_rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse({"detail": f"Rate limit exceeded: {exc.detail}"}, status_code=429)


limiter = Limiter(key_func=_real_ip)
app = FastAPI(title="The Gaffer", version="0.1.0", lifespan=_lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _on_rate_limit_exceeded)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key or secrets.token_urlsafe(32),
    same_site="lax",
    https_only=settings.environment == "production",
)


@app.middleware("http")
async def _request_logger(request: Request, call_next):
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        raise
    finally:
        latency_ms = round((time.monotonic() - start) * 1000)

    if request.url.path != "/health":
        log.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency_ms,
        )
    return response


class HistoryMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class AskRequest(BaseModel):
    question: str
    fpl_team_id: int | None = None
    history: list[HistoryMessage] = []


class FeedbackRequest(BaseModel):
    message: str
    email: str = ""


class ContactRequest(BaseModel):
    name: str
    email: str
    message: str


class ThumbsDownRequest(BaseModel):
    question: str
    answer: str
    comment: str = ""
    fpl_team_id: int | None = None


class AskResponse(BaseModel):
    answer: str
    league: str


def _sse(event: str, data: str) -> str:
    """Format a server-sent event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── Admin dashboard ────────────────────────────────────────────────────────────

_INSIGHTS_TIMEOUT = 30  # max seconds to wait for a query


@functools.cache
def _get_cw_client():
    """Lazily create the CloudWatch Logs client so a missing AWS config only
    breaks the admin endpoint, not the entire server at startup."""
    return boto3.client("logs", region_name=settings.cloudwatch_region)


_http_basic = HTTPBasic(auto_error=False)


def _admin_auth(credentials: HTTPBasicCredentials | None = Depends(_http_basic)) -> None:
    # No password configured → open access (dev / local mode)
    if not settings.admin_password:
        return
    pw = credentials.password if credentials else ""
    if not secrets.compare_digest(pw.encode(), settings.admin_password.encode()):
        raise HTTPException(
            status_code=401,
            detail="Incorrect password.",
            headers={"WWW-Authenticate": 'Basic realm="Gaffer Admin"'},
        )


async def _run_insights_query(query_string: str, hours: int) -> list[dict] | None:
    """Returns the first result row, [] if no data, or None on error."""
    end_time = int(time.time())
    start_time = end_time - hours * 3600
    cw = _get_cw_client()
    resp = await asyncio.to_thread(
        cw.start_query,
        logGroupName=settings.cloudwatch_log_group,
        startTime=start_time,
        endTime=end_time,
        queryString=query_string,
    )
    query_id = resp["queryId"]
    for _ in range(_INSIGHTS_TIMEOUT):
        await asyncio.sleep(1)
        result = await asyncio.to_thread(cw.get_query_results, queryId=query_id)
        if result["status"] == "Complete":
            return result["results"][0] if result["results"] else []
        if result["status"] in ("Failed", "Cancelled"):
            log.warning("admin.insights_failed", query=query_string, status=result["status"])
            return None
    log.warning("admin.insights_timeout", query=query_string)
    return None


def _field(row: list[dict], name: str, default: float = 0.0) -> float:
    for f in row:
        if f["field"] == name:
            try:
                return float(f["value"])
            except (ValueError, TypeError):
                return default
    return default


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


# ── Google sign-in ─────────────────────────────────────────────────────────────


@app.get("/auth/google/login")
async def google_login(request: Request):
    redirect_uri = f"{settings.public_base_url}/api/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/google/callback")
async def google_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo") or await oauth.google.userinfo(token=token)

    user_id = await app_db.get_or_create_user(
        google_sub=userinfo["sub"],
        email=userinfo["email"],
        name=userinfo.get("name", ""),
    )

    device_token = request.cookies.get(DEVICE_COOKIE)
    if device_token:
        await app_db.merge_device_into_user(device_token, user_id)

    request.session["user_id"] = user_id
    request.session["email"] = userinfo["email"]
    request.session["name"] = userinfo.get("name", "")

    return RedirectResponse(url="/")


@app.get("/auth/me")
async def auth_me(request: Request) -> dict:
    if "user_id" not in request.session:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "email": request.session.get("email"),
        "name": request.session.get("name"),
    }


@app.post("/auth/logout")
async def auth_logout(request: Request) -> dict[str, str]:
    request.session.clear()
    return {"status": "ok"}


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


@app.post("/contact")
async def contact(request: ContactRequest) -> dict[str, str]:
    if not request.message.strip() or not request.email.strip():
        raise HTTPException(status_code=422, detail="Name, email and message are required.")
    if not settings.resend_api_key or not settings.feedback_email:
        raise HTTPException(status_code=503, detail="Contact not configured.")

    body = f"Name: {request.name}\nEmail: {request.email}\n\nMessage:\n{request.message}"

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": "onboarding@resend.dev",
            "to": settings.feedback_email,
            "subject": f"[gaffer.io] Contact from {request.name}",
            "text": body,
        }
    )
    return {"status": "sent"}


@app.post("/fpl/thumbsdown")
async def thumbsdown(request: ThumbsDownRequest) -> dict[str, str]:
    log.info(
        "feedback.thumbsdown",
        question=request.question,
        fpl_team_id=request.fpl_team_id,
    )
    if not settings.resend_api_key or not settings.feedback_email:
        return {"status": "logged"}

    body_parts = [
        f"Question:\n{request.question}",
        f"\nAnswer:\n{request.answer}",
    ]
    if request.comment.strip():
        body_parts.append(f"\nWhat went wrong:\n{request.comment}")
    if request.fpl_team_id:
        body_parts.append(f"\nFPL Team ID: {request.fpl_team_id}")

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": "onboarding@resend.dev",
            "to": settings.feedback_email,
            "subject": "[gaffer.io] 👎 Bad answer",
            "text": "\n".join(body_parts),
        }
    )
    return {"status": "sent"}


@app.get("/admin/dashboard")
async def admin_dashboard(
    hours: int = 24,
    _: None = Depends(_admin_auth),
) -> dict:
    # Claude Sonnet 4.6 pricing (USD per 1M tokens)
    _PRICE = {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75}

    queries = [
        "filter event = 'ask.start' | stats count() as v",
        "filter event = 'ask.error' | stats count() as v",
        "filter event = 'ask.complete' | stats avg(latency_ms) as avg_ms, pct(latency_ms, 95) as p95_ms",  # noqa: E501
        "filter event = 'claude.tokens' | stats sum(input_tokens) as input_tok, sum(output_tokens) as output_tok, sum(cache_read_tokens) as cache_read_tok, sum(cache_write_tokens) as cache_write_tok",  # noqa: E501
        "filter event = 'feedback.thumbsdown' | stats count() as v",
        "filter event = 'player.photo_missing' | stats count() as v",
        "filter event = 'ask.start' | stats count_distinct(fpl_team_id) as v",
        "filter event = 'claude.tokens' | stats avg(tool_turns) as v",
        "filter event = 'claude.turn_limit_reached' | stats count() as v",
    ]

    try:
        rows = await asyncio.gather(*[_run_insights_query(q, hours) for q in queries])
    except Exception as exc:
        log.warning("admin.dashboard_error", error=str(exc))
        raise HTTPException(status_code=503, detail=f"CloudWatch Insights unavailable: {exc}")

    if any(r is None for r in rows):
        raise HTTPException(
            status_code=503,
            detail="One or more CloudWatch Insights queries failed — check region, log group, and IAM permissions.",  # noqa: E501
        )

    req, err, lat, tok, td, pm, uniq, turns, tlimit = rows

    total_requests = int(_field(req, "v"))
    error_count = int(_field(err, "v"))
    avg_ms = _field(lat, "avg_ms") or None
    p95_ms = _field(lat, "p95_ms") or None
    input_tok = int(_field(tok, "input_tok"))
    output_tok = int(_field(tok, "output_tok"))
    cache_read_tok = int(_field(tok, "cache_read_tok"))
    cache_write_tok = int(_field(tok, "cache_write_tok"))

    estimated_cost = (
        input_tok * _PRICE["input"]
        + output_tok * _PRICE["output"]
        + cache_read_tok * _PRICE["cache_read"]
        + cache_write_tok * _PRICE["cache_write"]
    ) / 1_000_000

    return {
        "period_hours": hours,
        "total_requests": total_requests,
        "error_count": error_count,
        "error_rate_pct": round(error_count / total_requests * 100, 1) if total_requests else 0,
        "avg_latency_ms": round(avg_ms) if avg_ms else None,
        "p95_latency_ms": round(p95_ms) if p95_ms else None,
        "input_tokens": input_tok,
        "output_tokens": output_tok,
        "cache_hit_pct": round(
            cache_read_tok / (input_tok + cache_read_tok + cache_write_tok) * 100
        )
        if (input_tok + cache_read_tok + cache_write_tok)
        else 0,  # noqa: E501
        "estimated_cost_usd": round(estimated_cost, 4),
        "unique_users": int(_field(uniq, "v")),
        "avg_tool_turns": round(_field(turns, "v", 0.0), 1),
        "turn_limit_hits": int(_field(tlimit, "v")),
        "thumbsdown_count": int(_field(td, "v")),
        "photo_missing_count": int(_field(pm, "v")),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.get("/admin/jobs")
async def admin_jobs(_: None = Depends(_admin_auth)) -> dict:
    """Job health (job_runs table), Postgres row counts, and Pinecone vector stats."""

    # ── job_runs: last completed run per job ──────────────────────────────────
    last_runs = await db_tool.execute("""
        SELECT DISTINCT ON (job_name)
            job_name,
            status,
            gw_number,
            details,
            started_at,
            EXTRACT(EPOCH FROM (completed_at - started_at))::float AS duration_s
        FROM job_runs
        WHERE status IN ('success', 'failure')
        ORDER BY job_name, started_at DESC
    """)

    # ── job_runs: 7-day counts per job ────────────────────────────────────────
    week_counts = await db_tool.execute("""
        SELECT job_name, status, COUNT(*) AS cnt
        FROM job_runs
        WHERE started_at > NOW() - INTERVAL '7 days'
          AND status != 'attempt'
        GROUP BY job_name, status
        ORDER BY job_name, status
    """)

    # ── Postgres ingestion row counts ─────────────────────────────────────────
    pg_counts = await db_tool.execute("""
        SELECT
            (SELECT COUNT(*)::int FROM players p
             JOIN seasons s ON s.id = p.season_id WHERE s.is_current) AS current_players,
            (SELECT COUNT(*)::int FROM gameweeks g
             JOIN seasons s ON s.id = g.season_id
             WHERE s.is_current AND g.is_finished = TRUE)             AS gameweeks_synced,
            (SELECT COUNT(*)::int FROM gw_player_stats gps
             JOIN seasons s ON s.id = gps.season_id WHERE s.is_current) AS gw_stats_rows,
            (SELECT COUNT(*)::int FROM seasons)                        AS total_seasons
    """)

    # ── Build per-job health dict ─────────────────────────────────────────────
    jobs: dict = {}
    if not last_runs.get("error"):
        for row in last_runs.get("rows", []):
            dur = row.get("duration_s")
            jobs[row["job_name"]] = {
                "last_run_at": row["started_at"],
                "last_status": row["status"],
                "last_gw": row.get("gw_number"),
                "last_duration_s": round(dur, 1) if dur is not None else None,
                "last_details": row.get("details") or {},
                "runs_7d": {"successes": 0, "failures": 0},
            }

    if not week_counts.get("error"):
        for row in week_counts.get("rows", []):
            jn = row["job_name"]
            if jn not in jobs:
                jobs[jn] = {
                    "last_run_at": None,
                    "last_status": None,
                    "last_gw": None,
                    "last_duration_s": None,
                    "last_details": {},
                    "runs_7d": {"successes": 0, "failures": 0},
                }
            if row["status"] == "success":
                jobs[jn]["runs_7d"]["successes"] = int(row["cnt"])
            elif row["status"] == "failure":
                jobs[jn]["runs_7d"]["failures"] = int(row["cnt"])

    # ── Postgres counts ───────────────────────────────────────────────────────
    postgres: dict = {}
    if not pg_counts.get("error") and pg_counts.get("rows"):
        postgres = pg_counts["rows"][0]

    # ── Pinecone vector stats ─────────────────────────────────────────────────
    pinecone_stats: dict | None = None
    if settings.pinecone_api_key and settings.pinecone_index_name:
        try:
            from pinecone import Pinecone as PineconeClient

            pc = PineconeClient(api_key=settings.pinecone_api_key)
            index = pc.Index(settings.pinecone_index_name)
            raw = await asyncio.to_thread(index.describe_index_stats)
            pinecone_stats = {
                "total_vectors": raw.total_vector_count,
                "namespaces": {
                    ns: info.vector_count for ns, info in (raw.namespaces or {}).items()
                },
            }
        except Exception as exc:
            log.warning("admin.pinecone_stats_failed", error=str(exc))

    return {
        "jobs": jobs,
        "postgres": postgres,
        "pinecone": pinecone_stats,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.post("/fpl/ask")
@limiter.limit("10/minute;50/hour")
async def fpl_ask(request: Request, body: AskRequest) -> StreamingResponse:
    if not body.question.strip():
        raise HTTPException(status_code=422, detail="Question must not be empty.")

    async def _generate():
        t0 = time.monotonic()
        tools_called: list[str] = []
        try:
            log.info(
                "ask.start",
                question=body.question,
                fpl_team_id=body.fpl_team_id,
            )

            history = [{"role": m.role, "content": m.content} for m in body.history]

            async def _mcp_call(name: str, inp: dict) -> dict:
                mcp_session = request.app.state.mcp_session
                result = await mcp_session.call_tool(name, arguments=inp)
                if result.content and isinstance(result.content[0], TextContent):
                    try:
                        return json.loads(result.content[0].text)
                    except json.JSONDecodeError:
                        return {"result": result.content[0].text}
                return {"error": True, "message": "No content returned from MCP tool"}

            async def _tracking_handler(name: str, inp: dict) -> dict:
                tools_called.append(name)
                return await _fpl_tool_handler(name, inp, body.fpl_team_id)

            async def _v2_handler(name: str, inp: dict) -> dict:
                if name in ("query_historical_stats", "query_press_conferences"):
                    tools_called.append(name)
                    return await _mcp_call(name, inp)
                return await _tracking_handler(name, inp)

            # Pre-fetch high-value context concurrently to skip round 1 tool calls.
            # Squad + chips + schedule all start at the same time.
            prefetch_coros: list = [fpl.get_gameweek_schedule()]
            if body.fpl_team_id:
                prefetch_coros += [
                    fpl.get_my_fpl_team(body.fpl_team_id),
                    fpl.get_chip_status(body.fpl_team_id),
                ]

            prefetch_results = await asyncio.gather(*prefetch_coros, return_exceptions=True)

            schedule_data = (
                prefetch_results[0] if not isinstance(prefetch_results[0], Exception) else None
            )
            squad_data = (
                prefetch_results[1]
                if (body.fpl_team_id and not isinstance(prefetch_results[1], Exception))
                else None
            )
            chip_data = (
                prefetch_results[2]
                if (
                    body.fpl_team_id
                    and len(prefetch_results) > 2
                    and not isinstance(prefetch_results[2], Exception)
                )
                else None
            )

            prefetched = {"gameweek_schedule": schedule_data}
            if squad_data:
                prefetched["squad"] = squad_data
            if chip_data:
                prefetched["chips"] = chip_data

            mcp_tool_defs = getattr(request.app.state, "mcp_tools", [])
            stream = await claude_client.ask(
                question=body.question,
                tool_definitions=fpl.get_tool_definitions() + mcp_tool_defs,
                tool_handler=_v2_handler,
                league="fpl",
                history=history,
                fpl_team_id=body.fpl_team_id,
                prefetched=prefetched,
            )

            async for event_type, data in stream:
                yield _sse(event_type, data)

            log.info(
                "ask.complete",
                question=body.question,
                fpl_team_id=body.fpl_team_id,
                tools=tools_called,
                latency_ms=round((time.monotonic() - t0) * 1000),
            )

        except Exception as e:
            log.error(
                "ask.error",
                question=body.question,
                error=str(e),
                latency_ms=round((time.monotonic() - t0) * 1000),
            )
            yield _sse("error", str(e))

    device_token = await app_db.get_or_create_device_token(request.cookies.get(DEVICE_COOKIE))

    response = StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
    response.set_cookie(
        DEVICE_COOKIE,
        device_token,
        max_age=_DEVICE_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
    )
    return response


async def _fpl_tool_handler(
    tool_name: str, tool_input: dict, fpl_team_id: int | None = None
) -> dict:
    handlers = {
        "get_my_fpl_team": lambda i: fpl.get_my_fpl_team(team_id_override=fpl_team_id),
        "get_chip_status": lambda i: fpl.get_chip_status(team_id_override=fpl_team_id),
        "get_gameweek_schedule": lambda i: fpl.get_gameweek_schedule(next_n=i.get("next_n", 8)),
        "get_fixtures": lambda i: fpl.get_fixtures(next_n=i.get("next_n", 10)),
        "get_standings": lambda i: fpl.get_standings(),
        "get_player_stats": lambda i: fpl.get_player_stats(player_name=i["player_name"]),
        "get_player_recent_form": lambda i: fpl.get_player_recent_form(
            player_name=i["player_name"],
            last_n=i.get("last_n", 5),
        ),
        "get_team_recent_fixtures": lambda i: fpl.get_team_recent_fixtures(
            team_name=i["team_name"],
            last_n=i.get("last_n", 5),
        ),
        "get_head_to_head": lambda i: fpl.get_head_to_head(
            team1_name=i["team1_name"],
            team2_name=i["team2_name"],
            last_n=i.get("last_n", 5),
        ),
        "get_team_all_fixtures": lambda i: fpl.get_team_all_fixtures(
            team_name=i["team_name"],
            next_n=i.get("next_n", 7),
        ),
        "get_player_vs_opponent": lambda i: fpl.get_player_vs_opponent(
            player_name=i["player_name"],
            opponent_name=i["opponent_name"],
            last_n=i.get("last_n", 5),
        ),
        "search_players_by_criteria": lambda i: fpl.search_players_by_criteria(
            position=i.get("position"),
            max_price=i.get("max_price"),
            min_price=i.get("min_price"),
            top_n=i.get("top_n", 10),
        ),
        "get_mini_league_standings": lambda i: fpl.get_mini_league_standings(
            league_id=i["league_id"],
            top_n=i.get("top_n", 20),
        ),
        "get_captain_options": lambda i: fpl.get_captain_options(
            player_names=i["player_names"],
        ),
        "get_player_xpts": lambda i: fpl.get_player_xpts(
            player_names=i.get("player_names"),
            position=i.get("position"),
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
