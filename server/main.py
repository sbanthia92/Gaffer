import boto3
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from server import claude_client, rag
from server.config import settings
from server.tools import fpl

app = FastAPI(title="The Gaffer", version="0.1.0")


class AskRequest(BaseModel):
    question: str
    fpl_team_id: int | None = None


class FeedbackRequest(BaseModel):
    message: str
    email: str = ""


class AskResponse(BaseModel):
    answer: str
    league: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@app.post("/feedback")
async def feedback(request: FeedbackRequest) -> dict[str, str]:
    if not request.message.strip():
        raise HTTPException(status_code=422, detail="Message must not be empty.")
    if not settings.feedback_email:
        raise HTTPException(status_code=503, detail="Feedback email not configured.")

    body = f"Message:\n{request.message}"
    if request.email:
        body += f"\n\nFrom: {request.email}"

    ses = boto3.client("ses", region_name="us-east-1")
    ses.send_email(
        Source=settings.feedback_email,
        Destination={"ToAddresses": [settings.feedback_email]},
        Message={
            "Subject": {"Data": "[gaffer.io] Bug report"},
            "Body": {"Text": {"Data": body}},
        },
    )
    return {"status": "sent"}


@app.post("/fpl/ask", response_model=AskResponse)
async def fpl_ask(request: AskRequest) -> AskResponse:
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="Question must not be empty.")

    # Layer 1 — RAG: retrieve historical context from Pinecone
    context = await rag.retrieve(
        query=request.question,
        namespace="fpl",
        top_k=5,
        recency_weight=0.3,
    )

    # Layer 2 — Claude: answer using live tools + RAG context
    answer = await claude_client.ask(
        question=request.question,
        tool_definitions=fpl.TOOL_DEFINITIONS,
        tool_handler=lambda name, inp: _fpl_tool_handler(name, inp, request.fpl_team_id),
        rag_context=context,
        league="fpl",
    )

    return AskResponse(answer=answer, league="fpl")


async def _fpl_tool_handler(tool_name: str, tool_input: dict, fpl_team_id: int | None = None) -> dict:
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
