from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from server.main import _fpl_tool_handler, app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_returns_environment() -> None:
    response = client.get("/health")
    assert "environment" in response.json()


def test_fpl_ask_returns_answer() -> None:
    with (
        patch("server.main.rag.retrieve", new=AsyncMock(return_value="Salah scored 2 vs City.")),
        patch(
            "server.main.claude_client.ask",
            new=AsyncMock(return_value="Captain Salah this week."),
        ),
    ):
        response = client.post("/fpl/ask", json={"question": "Should I captain Salah?"})

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Captain Salah this week."
    assert data["league"] == "fpl"


def test_fpl_ask_empty_question_returns_422() -> None:
    response = client.post("/fpl/ask", json={"question": ""})
    assert response.status_code == 422


def test_fpl_ask_missing_question_returns_422() -> None:
    response = client.post("/fpl/ask", json={})
    assert response.status_code == 422


def test_fpl_ask_passes_question_to_claude() -> None:
    mock_retrieve = AsyncMock(return_value="")
    mock_ask = AsyncMock(return_value="Transfer in Haaland.")

    with (
        patch("server.main.rag.retrieve", new=mock_retrieve),
        patch("server.main.claude_client.ask", new=mock_ask),
    ):
        client.post("/fpl/ask", json={"question": "Who should I transfer in?"})

    mock_ask.assert_awaited_once()
    call_kwargs = mock_ask.call_args.kwargs
    assert call_kwargs["question"] == "Who should I transfer in?"
    assert call_kwargs["league"] == "fpl"


@pytest.mark.asyncio
async def test_fpl_tool_handler_unknown_tool_raises() -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        await _fpl_tool_handler("nonexistent_tool", {})
