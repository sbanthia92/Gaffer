from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from server import claude_client, rag
from server.config import settings
from server.tools import fpl

app = FastAPI(title="The Gaffer", version="0.1.0")


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    league: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


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
        tool_handler=_fpl_tool_handler,
        rag_context=context,
        league="fpl",
    )

    return AskResponse(answer=answer, league="fpl")


async def _fpl_tool_handler(tool_name: str, tool_input: dict) -> dict:
    handlers = {
        "get_fixtures": lambda i: fpl.get_fixtures(next_n=i.get("next_n", 10)),
        "get_standings": lambda i: fpl.get_standings(),
        "get_player_stats": lambda i: fpl.get_player_stats(player_id=i["player_id"]),
        "get_odds": lambda i: fpl.get_odds(fixture_id=i["fixture_id"]),
        "get_player_recent_fixtures": lambda i: fpl.get_player_recent_fixtures(
            player_id=i["player_id"],
            last_n=i.get("last_n", 10),
        ),
    }
    handler = handlers.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    return await handler(tool_input)
