from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from server.claude_client import ask


def _make_usage() -> MagicMock:
    u = MagicMock()
    u.input_tokens = 100
    u.output_tokens = 50
    u.cache_read_input_tokens = 0
    u.cache_creation_input_tokens = 0
    u.server_tool_use = None
    return u


def _make_tool_use_response(tool_name: str, tool_input: dict, tool_use_id: str) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_use_id
    response = MagicMock(spec=anthropic.types.Message)
    response.stop_reason = "tool_use"
    response.content = [block]
    response.usage = _make_usage()
    return response


def _make_end_turn_response() -> MagicMock:
    """A response with stop_reason=end_turn and no text blocks (tool loop exits)."""
    response = MagicMock(spec=anthropic.types.Message)
    response.stop_reason = "end_turn"
    response.content = []
    response.usage = _make_usage()
    return response


def _make_stream_context(chunks: list[str]):
    """Return a mock async context manager that yields text chunks."""

    @asynccontextmanager
    async def _ctx():
        async def _text_stream():
            for c in chunks:
                yield c

        final = MagicMock(spec=anthropic.types.Message)
        final.usage = _make_usage()

        mock_stream = MagicMock()
        mock_stream.text_stream = _text_stream()
        mock_stream.get_final_message = AsyncMock(return_value=final)
        yield mock_stream

    return _ctx()


async def _collect(async_iter) -> str:
    """Drain an async iterator of (event_type, data) tuples and return concatenated chunks."""
    result = ""
    async for event_type, data in async_iter:
        if event_type == "chunk":
            result += data
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
async def test_ask_system_prompt_references_mcp_tools():
    """System prompt directs Claude to query_historical_stats and no longer to press RAG."""
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
            league="fpl",
        )
        await _collect(stream)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    system_text = "".join(block["text"] for block in call_kwargs["system"])
    assert "query_historical_stats" in system_text
    assert "query_press_conferences" not in system_text


def _make_block(block_type: str, **attrs) -> MagicMock:
    block = MagicMock()
    block.type = block_type
    for k, v in attrs.items():
        setattr(block, k, v)
    return block


def _make_response(stop_reason: str, content: list) -> MagicMock:
    response = MagicMock(spec=anthropic.types.Message)
    response.stop_reason = stop_reason
    response.content = content
    response.usage = _make_usage()
    return response


@pytest.mark.asyncio
async def test_ask_resumes_after_pause_turn():
    """pause_turn: the partial assistant turn is sent back and the loop continues."""
    paused = _make_response("pause_turn", [_make_block("server_tool_use", name="web_search")])
    end_turn = _make_end_turn_response()

    with patch("server.claude_client.anthropic.AsyncAnthropic") as mock_anthropic:
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(side_effect=[paused, end_turn])
        mock_client.messages.stream = MagicMock(return_value=_make_stream_context(["Done."]))

        stream = await ask(
            question="Is Saka fit?",
            tool_definitions=[],
            tool_handler=AsyncMock(return_value={}),
            league="fpl",
        )
        result = await _collect(stream)

    assert result == "Done."
    assert mock_client.messages.create.await_count == 2
    second_messages = mock_client.messages.create.call_args_list[1].kwargs["messages"]
    assert second_messages[-1] == {"role": "assistant", "content": paused.content}


@pytest.mark.asyncio
async def test_ask_emits_answer_written_after_web_search_without_restreaming():
    """If the final turn ran web searches, its text is the answer — no second stream call."""
    answer = _make_response(
        "end_turn",
        [
            _make_block("server_tool_use", name="web_search"),
            _make_block("web_search_tool_result"),
            _make_block("text", text="✅ Yes — Saka trained fully (BBC)."),
        ],
    )

    with patch("server.claude_client.anthropic.AsyncAnthropic") as mock_anthropic:
        mock_client = AsyncMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=answer)
        mock_client.messages.stream = MagicMock()

        stream = await ask(
            question="Is Saka fit?",
            tool_definitions=[],
            tool_handler=AsyncMock(return_value={}),
            league="fpl",
        )
        result = await _collect(stream)

    assert result == "✅ Yes — Saka trained fully (BBC)."
    mock_client.messages.stream.assert_not_called()


def test_system_prompt_requires_web_search_for_analysed_players():
    from server.claude_client import _build_system_prompt

    prompt = _build_system_prompt("fpl", 123)
    assert "web_search" in prompt
    assert "recommend bringing in" in prompt
