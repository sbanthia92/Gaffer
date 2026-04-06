from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from server.claude_client import ask


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


def _make_end_turn_response() -> MagicMock:
    """A response with stop_reason=end_turn and no text blocks (tool loop exits)."""
    response = MagicMock(spec=anthropic.types.Message)
    response.stop_reason = "end_turn"
    response.content = []
    return response


def _make_stream_context(chunks: list[str]):
    """Return a mock async context manager that yields text chunks."""

    @asynccontextmanager
    async def _ctx():
        async def _text_stream():
            for c in chunks:
                yield c

        mock_stream = MagicMock()
        mock_stream.text_stream = _text_stream()
        yield mock_stream

    return _ctx()


async def _collect(async_iter) -> str:
    """Drain an async iterator and return the concatenated string."""
    result = ""
    async for chunk in async_iter:
        result += chunk
    return result


@pytest.mark.asyncio
async def test_ask_streams_final_answer():
    end_turn = _make_end_turn_response()

    with patch("server.claude_client.anthropic.AsyncAnthropic") as mock_anthropic:
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=end_turn)
        mock_client.messages.stream = MagicMock(
            return_value=_make_stream_context(["Salah ", "is ", "great."])
        )

        stream = await ask(
            question="Should I captain Salah?",
            tool_definitions=[],
            tool_handler=AsyncMock(return_value={}),
            league="fpl",
        )
        result = await _collect(stream)

    assert result == "Salah is great."


@pytest.mark.asyncio
async def test_ask_runs_tool_then_streams():
    tool_response = _make_tool_use_response(
        tool_name="get_fixtures",
        tool_input={"next_n": 5},
        tool_use_id="tool_123",
    )
    end_turn = _make_end_turn_response()

    with patch("server.claude_client.anthropic.AsyncAnthropic") as mock_anthropic:
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(side_effect=[tool_response, end_turn])
        mock_client.messages.stream = MagicMock(
            return_value=_make_stream_context(["Based on fixtures, Salah looks good."])
        )

        mock_handler = AsyncMock(return_value={"fixtures": []})
        stream = await ask(
            question="Should I captain Salah?",
            tool_definitions=[{"name": "get_fixtures"}],
            tool_handler=mock_handler,
            league="fpl",
        )
        result = await _collect(stream)

    assert result == "Based on fixtures, Salah looks good."
    mock_handler.assert_awaited_once_with("get_fixtures", {"next_n": 5})


@pytest.mark.asyncio
async def test_ask_includes_rag_context_in_system_prompt():
    end_turn = _make_end_turn_response()

    with patch("server.claude_client.anthropic.AsyncAnthropic") as mock_anthropic:
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=end_turn)
        mock_client.messages.stream = MagicMock(return_value=_make_stream_context(["Answer."]))

        stream = await ask(
            question="How has Salah performed vs Man City?",
            tool_definitions=[],
            tool_handler=AsyncMock(return_value={}),
            rag_context="Salah scored 3 goals vs Man City in 2023-24.",
            league="fpl",
        )
        await _collect(stream)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert "Salah scored 3 goals vs Man City in 2023-24." in call_kwargs["system"]


@pytest.mark.asyncio
async def test_ask_empty_rag_context_handled():
    end_turn = _make_end_turn_response()

    with patch("server.claude_client.anthropic.AsyncAnthropic") as mock_anthropic:
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=end_turn)
        mock_client.messages.stream = MagicMock(
            return_value=_make_stream_context(["No context answer."])
        )

        stream = await ask(
            question="Who should I captain?",
            tool_definitions=[],
            tool_handler=AsyncMock(return_value={}),
            rag_context="",
            league="fpl",
        )
        result = await _collect(stream)

    assert result == "No context answer."
