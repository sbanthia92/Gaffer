import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from server.main import _fpl_tool_handler, _on_rate_limit_exceeded, app

client = TestClient(app)


def _mock_stream(text: str):
    """Return an async generator that yields the given text as a single chunk tuple."""

    async def _gen():
        yield "chunk", text
        yield "done", ""

    return _gen()


def _parse_sse(content: str) -> str:
    """Extract concatenated chunk data from an SSE response body."""
    result = ""
    for frame in content.split("\n\n"):
        if "event: chunk" in frame:
            data_line = next((ln for ln in frame.splitlines() if ln.startswith("data:")), None)
            if data_line:
                import json

                result += json.loads(data_line[5:].strip())
    return result


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_returns_environment() -> None:
    response = client.get("/health")
    assert "environment" in response.json()


def test_fpl_ask_streams_answer() -> None:
    with (
        patch("server.main.rag.retrieve", new=AsyncMock(return_value="")),
        patch(
            "server.main.claude_client.ask",
            new=AsyncMock(return_value=_mock_stream("Captain Salah this week.")),
        ),
    ):
        response = client.post("/fpl/ask", json={"question": "Should I captain Salah?"})

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert _parse_sse(response.text) == "Captain Salah this week."


def test_fpl_ask_empty_question_returns_422() -> None:
    response = client.post("/fpl/ask", json={"question": ""})
    assert response.status_code == 422


def test_fpl_ask_missing_question_returns_422() -> None:
    response = client.post("/fpl/ask", json={})
    assert response.status_code == 422


def test_fpl_ask_passes_question_to_claude() -> None:
    mock_retrieve = AsyncMock(return_value="")
    mock_ask = AsyncMock(return_value=_mock_stream("Transfer in Haaland."))

    with (
        patch("server.main.rag.retrieve", new=mock_retrieve),
        patch("server.main.claude_client.ask", new=mock_ask),
    ):
        client.post("/fpl/ask", json={"question": "Who should I transfer in?"})

    mock_ask.assert_awaited_once()
    call_kwargs = mock_ask.call_args.kwargs
    assert call_kwargs["question"] == "Who should I transfer in?"
    assert call_kwargs["league"] == "fpl"


def test_rate_limit_handler_returns_429() -> None:
    # Build a minimal fake exception with the same interface the handler uses
    exc = Exception()
    exc.detail = "10 per 1 minute"
    mock_request = object()
    response = _on_rate_limit_exceeded(mock_request, exc)
    assert isinstance(response, JSONResponse)
    assert response.status_code == 429
    assert "Rate limit exceeded" in json.loads(response.body)["detail"]


@pytest.mark.asyncio
async def test_fpl_tool_handler_unknown_tool_raises() -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        await _fpl_tool_handler("nonexistent_tool", {})
