from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from server.claude_client import ask


def _make_text_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock(spec=anthropic.types.Message)
    response.stop_reason = "end_turn"
    response.content = [block]
    return response


def _make_tool_use_response(tool_name: str, tool_input: dict, tool_use_id: str) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_use_id
    response = MagicMock(spec=anthropic.types.Message)
    response.stop_reason = "tool_use"
    response.content = [block]
    return response


@pytest.mark.asyncio
async def test_ask_returns_text_on_end_turn():
    mock_response = _make_text_response("Salah is a great captain pick.")

    with patch("server.claude_client.anthropic.AsyncAnthropic") as mock_anthropic:
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await ask(
            question="Should I captain Salah?",
            tool_definitions=[],
            tool_handler=AsyncMock(return_value={}),
            league="fpl",
        )

    assert result == "Salah is a great captain pick."


@pytest.mark.asyncio
async def test_ask_executes_tool_and_returns_final_answer():
    tool_response = _make_tool_use_response(
        tool_name="get_fixtures",
        tool_input={"next_n": 5},
        tool_use_id="tool_123",
    )
    final_response = _make_text_response("Based on fixtures, Salah looks good.")

    with patch("server.claude_client.anthropic.AsyncAnthropic") as mock_anthropic:
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(side_effect=[tool_response, final_response])

        mock_handler = AsyncMock(return_value={"response": []})
        result = await ask(
            question="Should I captain Salah?",
            tool_definitions=[{"name": "get_fixtures"}],
            tool_handler=mock_handler,
            league="fpl",
        )

    assert result == "Based on fixtures, Salah looks good."
    mock_handler.assert_awaited_once_with("get_fixtures", {"next_n": 5})


@pytest.mark.asyncio
async def test_ask_includes_rag_context_in_system_prompt():
    mock_response = _make_text_response("Answer with context.")

    with patch("server.claude_client.anthropic.AsyncAnthropic") as mock_anthropic:
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        await ask(
            question="How has Salah performed vs Man City?",
            tool_definitions=[],
            tool_handler=AsyncMock(return_value={}),
            rag_context="Salah scored 3 goals vs Man City in 2023-24.",
            league="fpl",
        )

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert "Salah scored 3 goals vs Man City in 2023-24." in call_kwargs["system"]


@pytest.mark.asyncio
async def test_ask_empty_rag_context_handled():
    mock_response = _make_text_response("No historical context answer.")

    with patch("server.claude_client.anthropic.AsyncAnthropic") as mock_anthropic:
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await ask(
            question="Who should I captain?",
            tool_definitions=[],
            tool_handler=AsyncMock(return_value={}),
            rag_context="",
            league="fpl",
        )

    assert result == "No historical context answer."
