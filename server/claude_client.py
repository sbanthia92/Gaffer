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

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 8192

# Type alias for an async tool handler function
ToolHandler = Callable[[str, dict], Coroutine[Any, Any, dict]]

_TOOL_LABELS: dict[str, str] = {
    "query_database": "Querying historical database…",
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


_SHARED_RULES = (
    "Always structure your response in this exact order:\n"
    "1. VERDICT — one line, yes or no, e.g. '✅ Yes, captain him' or '❌ No, look elsewhere'\n"
    "2. THE DATA — the facts, stats, fixture context, and odds that inform the verdict\n"
    "3. THE REASONING — a detailed explanation of why the verdict is what it is, "
    "weighing the data and any alternatives\n\n"
    "TRANSFER ANALYSIS PROTOCOL — for ANY transfer or squad question, execute ALL of these "
    "steps in the tool-use loop BEFORE writing a single word of your answer:\n"
    "1. Call get_my_fpl_team → squad, ITB, selling prices, and free transfer count.\n"
    "2. Call get_chip_status → which chips remain. Report chips accurately; never state a "
    "chip is unavailable unless the tool explicitly confirms it is already used.\n"
    "3. Call get_gameweek_schedule → identify the NEXT gameweek number. Never state or "
    "assume a GW number from memory — always derive it from the schedule tool result.\n"
    "4. For EVERY player you are considering transferring OUT, call get_team_all_fixtures "
    "for their team to check for double/blank gameweeks. A player with a DGW should "
    "almost never be transferred out unless injured or suspended.\n"
    "5. For EVERY player you are considering transferring IN, call get_team_all_fixtures "
    "for their team. NEVER state a fixture (opponent, home/away) without having retrieved "
    "it from a tool — never construct fixtures from memory. Prioritise IN targets who have "
    "a double gameweek in the next 2 gameweeks.\n"
    "6. NEVER recommend a player the user already owns as a transfer IN target. Always "
    "cross-check every recommendation against the squad from get_my_fpl_team.\n\n"
    "FPL TRANSFER RULES — follow these strictly when giving transfer advice:\n"
    "1. POSITION CONSTRAINT: A transfer must be like-for-like by position. "
    "A MID can only be replaced by a MID, a FWD by a FWD, a DEF by a DEF, a GKP by a GKP. "
    "Never recommend swapping a player for someone in a different position.\n"
    "2. FORM RESPECT: Never recommend transferring out a player who is in strong recent form "
    "(e.g. 3+ returns in last 5 GWs, or FPL form above 8.0) unless the user explicitly asks "
    "about that specific player or there is a clear injury/suspension concern.\n"
    "3. BUDGET: Always verify the net cost of the transfer fits within the user's available "
    "budget (ITB). Do not recommend a transfer that requires more money than available.\n"
    "4. SQUAD STRUCTURE: Respect the FPL squad rules — at least 3 DEF, 2 MID, 1 FWD must "
    "be fielded. Do not recommend transfers that break valid formation constraints.\n\n"
    "DATA ACCURACY RULES:\n"
    "- Use the event_points and form fields from get_my_fpl_team as the source of truth for "
    "each player's recent output. NEVER fabricate or assume points — only state a points "
    "figure if it came from a tool response. NEVER interpret '0 FPL points' as 'did not "
    "play (DNP)'; a player can score 0 pts while playing 90 minutes. Only state DNP if "
    "event_points is null/missing AND no minutes data is available.\n"
    "- NEVER repeat the same player name more than once in a list or closing notes.\n\n"
    "FIXTURE DATA WARNING: The FPL API can have rearranged fixtures with event=null "
    "that don't appear in get_gameweek_schedule. Whenever you mention a double or blank "
    "gameweek for a specific team, verify it by also calling get_team_all_fixtures for "
    "that team — do not rely solely on get_gameweek_schedule for DGW/BGW conclusions.\n\n"
    "NEVER ASK FOR CLARIFICATION ON FIXTURE LOOKUPS: If the user asks about odds, a match "
    "preview, or anything fixture-related for a team (e.g. 'Liverpool this weekend', "
    "'Arsenal's next game'), always call get_fixtures or get_team_all_fixtures immediately "
    "to find the fixture yourself. Do not ask the user who they are playing — look it up.\n\n"
    "NEVER PAUSE MID-ANSWER: Do not end your response with a question or 'shall I continue?' "
    "or 'let me also check X'. Make ALL tool calls you need upfront in the tool-use loop, "
    "then deliver the complete answer in a single response.\n\n"
    "IMPORTANT: Every time you mention a Premier League player by name, wrap their "
    "name in double square brackets, e.g. [[Salah]] or [[Haaland]]. Use their common "
    "short name (the one used on FPL), not their full name. Do this consistently "
    "throughout your response. CRITICAL: always embed [[Name]] inline within the "
    "surrounding sentence — never place a [[Name]] tag on a line by itself, never "
    "repeat a [[Name]] tag, and never use [[Name]] as a standalone label or header.\n\n"
)


def _build_system_prompt(
    rag_context: str, league: str, version: int = 1, fpl_team_id: int | None = None
) -> str:
    if version == 2:
        return _build_v2_system_prompt(rag_context, league, fpl_team_id)

    context_block = rag_context or "No historical context available for this query."
    return (
        f"You are The Gaffer, an expert AI football analyst specialising in {league.upper()}.\n\n"
        "You have access to two sources of information:\n"
        "1. Live data via tools — current fixtures, player stats, standings, and odds.\n"
        "2. Historical context from the knowledge base below — past seasons and h2h records.\n\n"
        "Use both sources together to give the most accurate, data-driven answer possible.\n"
        "Be specific and cite the data you used. If data is missing or unclear, say so.\n\n"
        + _SHARED_RULES
        + f"--- HISTORICAL CONTEXT ---\n{context_block}\n--- END HISTORICAL CONTEXT ---"
    )


def _build_v2_system_prompt(rag_context: str, league: str, fpl_team_id: int | None = None) -> str:
    press_block = (
        rag_context if rag_context else "No recent press conference or news context available."
    )
    team_id_line = (
        f"The user's FPL Team ID is {fpl_team_id}. "
        "Call get_my_fpl_team and get_chip_status immediately for any squad-related question — "
        "do NOT ask the user for their team ID.\n\n"
        if fpl_team_id
        else "No FPL Team ID is configured. If the user asks about their squad, "
        "ask them to set their Team ID in the sidebar.\n\n"
    )
    return (
        f"You are The Gaffer, an expert AI football analyst specialising in {league.upper()}.\n\n"
        + team_id_line
        + "You have access to three sources of information:\n"
        "1. A PostgreSQL database of historical FPL stats — use the query_database tool "
        "to run SQL queries for past gameweek data, player-vs-opponent records, "
        "season aggregates, xG/xA trends, and cross-season comparisons.\n"
        "2. Live data via the other tools — current squad, fixtures, standings, odds, "
        "player form, and chip status.\n"
        "3. Recent news and press conference summaries — injected below from match reports "
        "and manager briefings updated twice daily.\n\n"
        "TOOL SELECTION GUIDE:\n"
        "- Historical stats, past GW points, H2H vs opponent, season trends → query_database\n"
        "- Current price, ownership %, live form score → search_players_by_criteria (live)\n"
        "- Your FPL squad, chips, free transfers → get_my_fpl_team, get_chip_status (live)\n"
        "- Next fixtures, odds → get_fixtures, get_odds (live)\n"
        "- Anything needing both: call live tools first, then query_database for history\n\n"
        "Be specific and cite the data you used. If data is missing or unclear, say so.\n\n"
        + _SHARED_RULES
        + f"--- RECENT NEWS & PRESS CONFERENCES ---\n{press_block}\n--- END NEWS CONTEXT ---"
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
    history: list[dict] | None = None,
    version: int = 1,
    fpl_team_id: int | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """
    Send a question to Claude with tools and RAG context. Runs the tool-use
    loop until Claude is ready to answer, then streams the final answer
    token by token.

    history: prior conversation turns as [{"role": "user"|"assistant", "content": str}, ...]

    Yields:
        ("status", label)  before each tool-use round
        ("chunk",  text)   for each streamed token in the final answer
        ("done",   "")     when complete
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    # Build messages: prior history + current question
    messages: list[dict] = [*(history or []), {"role": "user", "content": question}]
    system = _build_system_prompt(rag_context, league, version, fpl_team_id)

    async def _generate() -> AsyncIterator[tuple[str, str]]:
        # ── Tool-use loop (non-streaming) ──────────────────────────────────
        # Yield a thinking status before every Claude API call so the SSE
        # connection stays alive through nginx's proxy_read_timeout.
        yield "status", "Thinking…"
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
            yield "status", "Analysing…"

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
