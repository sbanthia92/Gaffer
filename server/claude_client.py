"""
Claude client — sport-agnostic Anthropic SDK wrapper.

Handles the full tool-use loop:
  1. Send question + RAG context + tool definitions to Claude
  2. Execute any tool calls Claude requests (concurrently within each round)
  3. Send results back to Claude
  4. Stream the final text answer token by token

Yields (event_type, data) tuples:
  - ("status", label_str)  — during tool-use rounds, before each round executes
  - ("chunk",  text_str)   — during final streaming answer
  - ("done",   "")         — when complete

The caller is responsible for providing the right tools and RAG context
for the sport/league in question. Nothing in here is FPL-specific.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

import anthropic

from server.config import settings

_MODEL = "claude-opus-4-6"
_MAX_TOKENS = 4096

# Type alias for an async tool handler function
ToolHandler = Callable[[str, dict], Coroutine[Any, Any, dict]]

_TOOL_LABELS: dict[str, str] = {
    "get_my_fpl_team": "Fetching your FPL squad…",
    "get_chip_status": "Checking your chip availability…",
    "get_gameweek_schedule": "Loading gameweek schedule…",
    "search_player": "Looking up player stats…",
    "search_team": "Looking up team data…",
    "get_fixtures": "Checking upcoming fixtures…",
    "get_standings": "Fetching league standings…",
    "get_player_stats": "Fetching player stats…",
    "get_player_recent_form": "Analysing recent form…",
    "get_team_recent_fixtures": "Reviewing recent fixtures…",
    "get_head_to_head": "Checking head-to-head record…",
    "get_team_all_fixtures": "Loading fixture list…",
    "get_player_vs_opponent": "Analysing player vs opponent…",
    "get_odds": "Fetching match odds…",
    "search_players_by_criteria": "Searching for players…",
}


def _tool_status(tool_blocks: list) -> str:
    """Return a human-readable status label for a batch of tool calls."""
    if len(tool_blocks) == 1:
        return _TOOL_LABELS.get(tool_blocks[0].name, "Gathering data…")
    labels = [_TOOL_LABELS.get(b.name, b.name) for b in tool_blocks]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique = [l for l in labels if not (l in seen or seen.add(l))]  # noqa: E741
    return " · ".join(unique)


def _build_system_prompt(rag_context: str, league: str) -> str:
    context_block = rag_context or "No historical context available for this query."
    return (
        f"You are The Gaffer, an expert AI football analyst specialising in {league.upper()}.\n\n"
        "You have access to two sources of information:\n"
        "1. Live data via tools — current fixtures, player stats, standings, and odds.\n"
        "2. Historical context from the knowledge base below — past seasons and h2h records.\n\n"
        "Use both sources together to give the most accurate, data-driven answer possible.\n"
        "Be specific and cite the data you used. If data is missing or unclear, say so.\n\n"
        "Always structure your response in this exact order:\n"
        "1. VERDICT — one line, yes or no, e.g. '✅ Yes, captain him' or '❌ No, look elsewhere'\n"
        "2. THE DATA — the facts, stats, fixture context, and odds that inform the verdict\n"
        "3. THE REASONING — a detailed explanation of why the verdict is what it is, "
        "weighing the data and any alternatives\n\n"
        "IMPORTANT: Every time you mention a Premier League player by name, wrap their "
        "name in double square brackets, e.g. [[Salah]] or [[Haaland]]. Use their common "
        "short name (the one used on FPL), not their full name. Do this consistently "
        "throughout your response. CRITICAL: always embed [[Name]] inline within the "
        "surrounding sentence — never place a [[Name]] tag on a line by itself, never "
        "repeat a [[Name]] tag, and never use [[Name]] as a standalone label or header.\n\n"
        f"--- HISTORICAL CONTEXT ---\n{context_block}\n--- END HISTORICAL CONTEXT ---"
    )


async def _run_tool_round(
    response: anthropic.types.Message,
    tool_handler: ToolHandler,
) -> list[dict]:
    """Execute all tool calls in a response concurrently and return tool_result blocks."""
    tool_blocks = [b for b in response.content if b.type == "tool_use"]

    async def _call(block):
        try:
            result = await asyncio.wait_for(tool_handler(block.name, block.input), timeout=20.0)
        except TimeoutError:
            result = {
                "error": True,
                "message": f"Tool {block.name} timed out — use available data to answer.",
            }
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": json.dumps(result),
        }

    return list(await asyncio.gather(*(_call(b) for b in tool_blocks)))


async def ask(
    question: str,
    tool_definitions: list[dict],
    tool_handler: ToolHandler,
    rag_context: str = "",
    league: str = "fpl",
) -> AsyncIterator[tuple[str, str]]:
    """
    Send a question to Claude with tools and RAG context. Runs the tool-use
    loop until Claude is ready to answer, then streams the final answer
    token by token.

    Yields:
        ("status", label)  before each tool-use round
        ("chunk",  text)   for each streamed token in the final answer
        ("done",   "")     when complete
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    messages: list[dict] = [{"role": "user", "content": question}]
    system = _build_system_prompt(rag_context, league)

    async def _generate() -> AsyncIterator[tuple[str, str]]:
        # ── Tool-use loop (non-streaming) ──────────────────────────────────
        while True:
            response = await client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=system,
                tools=tool_definitions,
                messages=messages,
            )

            if response.stop_reason != "tool_use":
                break

            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            yield "status", _tool_status(tool_blocks)

            messages.append({"role": "assistant", "content": response.content})
            tool_results = await _run_tool_round(response, tool_handler)
            messages.append({"role": "user", "content": tool_results})

        # ── Stream the final answer ────────────────────────────────────────
        async with client.messages.stream(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system,
            tools=tool_definitions,
            tool_choice={"type": "none"},
            messages=messages,
        ) as stream:
            async for chunk in stream.text_stream:
                yield "chunk", chunk

        yield "done", ""

    return _generate()


def _extract_text(response: anthropic.types.Message) -> str:
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return ""
