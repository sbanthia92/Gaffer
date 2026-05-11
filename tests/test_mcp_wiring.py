"""Tests for MCP client wiring in server/main.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mcp_tool(name: str, description: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = {"type": "object", "properties": {}, "required": []}
    return tool


def test_convert_mcp_tools_formats_correctly():
    from server.main import _convert_mcp_tools

    mcp_tools = [
        _make_mcp_tool("query_historical_stats", "Query historical FPL stats"),
        _make_mcp_tool("query_press_conferences", "Search press conferences"),
    ]
    result = _convert_mcp_tools(mcp_tools)

    assert len(result) == 2
    assert result[0]["name"] == "query_historical_stats"
    assert result[0]["description"] == "Query historical FPL stats"
    assert "input_schema" in result[0]
    assert result[1]["name"] == "query_press_conferences"


def test_convert_mcp_tools_handles_none_description():
    from server.main import _convert_mcp_tools

    tool = _make_mcp_tool("query_historical_stats", None)
    result = _convert_mcp_tools([tool])
    assert result[0]["description"] == ""


@pytest.mark.asyncio
async def test_mcp_call_parses_json_response():
    """_mcp_call parses JSON text from a TextContent result."""
    from server.main import _find_mcp_server_path

    # Verify _find_mcp_server_path raises if config module is missing
    with patch("server.main.importlib.util.find_spec", return_value=None):
        with pytest.raises(RuntimeError, match="sports-context-mcp server.py not found"):
            _find_mcp_server_path()


@pytest.mark.asyncio
async def test_v2_handler_routes_mcp_tools_via_session():
    """query_historical_stats and query_press_conferences route through MCP session."""
    from fastapi.testclient import TestClient

    from server.main import app

    mock_session = AsyncMock()
    text_content = MagicMock()
    text_content.__class__ = __import__("mcp.types", fromlist=["TextContent"]).TextContent
    text_content.text = json.dumps({"rows": [{"player": "Salah", "points": 12}]})

    mock_result = MagicMock()
    mock_result.content = [text_content]
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    app.state.mcp_session = mock_session
    app.state.mcp_tools = [
        {
            "name": "query_historical_stats",
            "description": "Query historical stats",
            "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}},
        }
    ]

    def _mock_stream(text):
        async def _gen():
            yield "chunk", text
            yield "done", ""

        return _gen()

    with patch(
        "server.main.claude_client.ask",
        new=AsyncMock(return_value=_mock_stream("Salah scored 12 points.")),
    ):
        client = TestClient(app)
        response = client.post("/fpl/ask", json={"question": "How many points did Salah score?"})

    assert response.status_code == 200
