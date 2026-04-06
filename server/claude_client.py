"""
Claude client — sport-agnostic Anthropic SDK wrapper.

Handles the full tool-use loop:
  1. Send question + RAG context + tool definitions to Claude
  2. Execute any tool calls Claude requests (concurrently within each round)
  3. Send results back to Claude
  4. Stream the final text answer token by token

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
        f"--- HISTORICAL CONTEXT ---\n{context_block}\n--- END HISTORICAL CONTEXT ---"
    )


async def _run_tool_round(
    response: anthropic.types.Message,
    tool_handler: ToolHandler,
) -> list[dict]:
    """Execute all tool calls in a response concurrently and return tool_result blocks."""
    tool_blocks = [b for b in response.content if b.type == "tool_use"]

    async def _call(block):
        result = await tool_handler(block.name, block.input)
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
) -> AsyncIterator[str]:
    """
    Send a question to Claude with tools and RAG context. Runs the tool-use
    loop until Claude is ready to answer, then streams the final answer
    token by token.

    Yields:
        Text chunks as Claude generates the final answer.
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    messages: list[dict] = [{"role": "user", "content": question}]
    system = _build_system_prompt(rag_context, league)

    # ── Tool-use loop (non-streaming) ──────────────────────────────────────
    # Run until Claude stops requesting tools, then stream the final answer.
    while True:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system,
            tools=tool_definitions,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = await _run_tool_round(response, tool_handler)
            messages.append({"role": "user", "content": tool_results})
            continue

        # Claude is done with tools — stream the final answer
        break

    # ── Stream the final answer ────────────────────────────────────────────
    async def _stream() -> AsyncIterator[str]:
        async with client.messages.stream(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=messages,
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk

    return _stream()


def _extract_text(response: anthropic.types.Message) -> str:
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return ""
