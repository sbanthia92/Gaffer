"""
Claude client — sport-agnostic Anthropic SDK wrapper.

Handles the full tool-use loop:
  1. Send question + RAG context + tool definitions to Claude
  2. Execute any tool calls Claude requests
  3. Send results back to Claude
  4. Return the final answer

The caller is responsible for providing the right tools and RAG context
for the sport/league in question. Nothing in here is FPL-specific.
"""

import json
from collections.abc import Callable, Coroutine
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


async def ask(
    question: str,
    tool_definitions: list[dict],
    tool_handler: ToolHandler,
    rag_context: str = "",
    league: str = "fpl",
) -> str:
    """
    Send a question to Claude with tools and RAG context, run the tool-use
    loop until Claude produces a final answer, and return it.

    Args:
        question: The natural language question from the user.
        tool_definitions: List of tool schemas in Anthropic format.
        tool_handler: Async function that executes a tool by name and input.
        rag_context: Pre-retrieved historical context from Pinecone.
        league: The league/sport namespace — used for the system prompt.

    Returns:
        Claude's final text answer.
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    messages: list[dict] = [{"role": "user", "content": question}]
    system = _build_system_prompt(rag_context, league)

    while True:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system,
            tools=tool_definitions,
            messages=messages,
        )

        # Claude is done — return the text answer
        if response.stop_reason == "end_turn":
            return _extract_text(response)

        # Claude wants to call tools
        if response.stop_reason == "tool_use":
            # Append Claude's response (with tool_use blocks) to the conversation
            messages.append({"role": "assistant", "content": response.content})

            # Execute each tool call and collect results
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = await tool_handler(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        }
                    )

            # Send tool results back to Claude
            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason — return whatever text we have
        return _extract_text(response)


def _extract_text(response: anthropic.types.Message) -> str:
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return ""
