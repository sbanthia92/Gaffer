import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse, RedirectResponse
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
    with patch(
        "server.main.claude_client.ask",
        new=AsyncMock(return_value=_mock_stream("Captain Salah this week.")),
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


def test_fpl_ask_sets_device_cookie() -> None:
    with patch(
        "server.main.claude_client.ask",
        new=AsyncMock(return_value=_mock_stream("Captain Salah this week.")),
    ):
        response = client.post("/fpl/ask", json={"question": "Should I captain Salah?"})

    assert "gaffer_device" in response.cookies
    assert len(response.cookies["gaffer_device"]) > 20


def test_fpl_ask_reuses_existing_device_cookie() -> None:
    client.cookies.set("gaffer_device", "existing-token-value")
    try:
        with patch(
            "server.main.claude_client.ask",
            new=AsyncMock(return_value=_mock_stream("Captain Salah this week.")),
        ):
            response = client.post("/fpl/ask", json={"question": "Should I captain Salah?"})
        assert response.cookies["gaffer_device"] == "existing-token-value"
    finally:
        client.cookies.clear()


def test_fpl_ask_passes_question_to_claude() -> None:
    mock_ask = AsyncMock(return_value=_mock_stream("Transfer in Haaland."))

    with patch("server.main.claude_client.ask", new=mock_ask):
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


def test_auth_me_unauthenticated_by_default() -> None:
    response = TestClient(app).get("/auth/me")
    assert response.json() == {"authenticated": False}


def test_google_login_redirects_to_google() -> None:
    fresh_client = TestClient(app)
    mock_redirect = AsyncMock(
        return_value=RedirectResponse(url="https://accounts.google.com/o/oauth2/auth")
    )

    with patch("server.main.oauth.google.authorize_redirect", new=mock_redirect):
        response = fresh_client.get("/auth/google/login", follow_redirects=False)

    assert response.status_code in (302, 307)
    mock_redirect.assert_awaited_once()
    redirect_uri = mock_redirect.call_args.args[1]
    assert redirect_uri.endswith("/api/auth/google/callback")


def test_google_callback_sets_session_and_auth_me_reflects_it() -> None:
    fresh_client = TestClient(app)
    mock_token = {
        "userinfo": {"sub": "google-123", "email": "person@example.com", "name": "Person"}
    }

    with (
        patch(
            "server.main.oauth.google.authorize_access_token",
            new=AsyncMock(return_value=mock_token),
        ),
        patch("server.main.app_db.get_or_create_user", new=AsyncMock(return_value=42)),
        patch("server.main.app_db.merge_device_into_user", new=AsyncMock()) as mock_merge,
    ):
        callback_response = fresh_client.get("/auth/google/callback", follow_redirects=False)

    assert callback_response.status_code in (302, 307)
    mock_merge.assert_not_awaited()  # no device cookie present on this fresh client

    me = fresh_client.get("/auth/me")
    assert me.json() == {"authenticated": True, "email": "person@example.com", "name": "Person"}

    logout = fresh_client.post("/auth/logout")
    assert logout.json() == {"status": "ok"}

    me_after_logout = fresh_client.get("/auth/me")
    assert me_after_logout.json() == {"authenticated": False}


def test_fpl_ask_persists_conversation_when_session_id_given() -> None:
    with (
        patch(
            "server.main.claude_client.ask",
            new=AsyncMock(return_value=_mock_stream("Captain Salah this week.")),
        ),
        patch(
            "server.main.app_db.upsert_conversation", new=AsyncMock(return_value=99)
        ) as mock_upsert,
        patch("server.main.app_db.save_chat_messages", new=AsyncMock()) as mock_save,
    ):
        response = client.post(
            "/fpl/ask",
            json={"question": "Should I captain Salah?", "session_id": "thread-1"},
        )

    assert response.status_code == 200
    mock_upsert.assert_awaited_once()
    assert mock_upsert.call_args.kwargs["client_session_id"] == "thread-1"
    mock_save.assert_awaited_once_with(99, "Should I captain Salah?", "Captain Salah this week.")


def test_fpl_ask_skips_persistence_without_session_id() -> None:
    with (
        patch(
            "server.main.claude_client.ask",
            new=AsyncMock(return_value=_mock_stream("Captain Salah this week.")),
        ),
        patch("server.main.app_db.upsert_conversation", new=AsyncMock()) as mock_upsert,
        patch("server.main.app_db.save_chat_messages", new=AsyncMock()) as mock_save,
    ):
        response = client.post("/fpl/ask", json={"question": "Should I captain Salah?"})

    assert response.status_code == 200
    mock_upsert.assert_not_awaited()
    mock_save.assert_not_awaited()


def test_fpl_ask_persist_failure_does_not_break_response() -> None:
    with (
        patch(
            "server.main.claude_client.ask",
            new=AsyncMock(return_value=_mock_stream("Captain Salah this week.")),
        ),
        patch(
            "server.main.app_db.upsert_conversation",
            new=AsyncMock(side_effect=RuntimeError("db exploded")),
        ),
    ):
        response = client.post(
            "/fpl/ask",
            json={"question": "Should I captain Salah?", "session_id": "thread-2"},
        )

    assert response.status_code == 200
    assert _parse_sse(response.text) == "Captain Salah this week."


def test_google_callback_merges_existing_device_token() -> None:
    fresh_client = TestClient(app)
    fresh_client.cookies.set("gaffer_device", "some-device-token")
    mock_token = {"userinfo": {"sub": "google-456", "email": "b@example.com", "name": "B"}}

    with (
        patch(
            "server.main.oauth.google.authorize_access_token",
            new=AsyncMock(return_value=mock_token),
        ),
        patch("server.main.app_db.get_or_create_user", new=AsyncMock(return_value=7)),
        patch("server.main.app_db.merge_device_into_user", new=AsyncMock()) as mock_merge,
    ):
        fresh_client.get("/auth/google/callback", follow_redirects=False)

    mock_merge.assert_awaited_once_with("some-device-token", 7)
