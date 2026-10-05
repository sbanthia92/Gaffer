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


def test_fpl_ask_prefetches_standings() -> None:
    mock_ask = AsyncMock(return_value=_mock_stream("ok"))
    standings = {"standings": [{"team": "Leeds", "rank": 9}]}

    with (
        patch("server.main.claude_client.ask", new=mock_ask),
        patch("server.main.fpl.get_standings", new=AsyncMock(return_value=standings)),
        patch(
            "server.main.fpl.get_gameweek_schedule",
            new=AsyncMock(side_effect=RuntimeError("fpl down")),
        ),
    ):
        client.post("/fpl/ask", json={"question": "Is a Leeds defender worth owning?"})

    # A failed pre-fetch is dropped; the rest still reach Claude.
    assert mock_ask.call_args.kwargs["prefetched"] == {"standings": standings}


def _ask_with_question_count(count, auth=None, **settings_overrides):
    with (
        patch(
            "server.main.claude_client.ask",
            new=AsyncMock(return_value=_mock_stream("Captain Salah this week.")),
        ),
        patch("server.main.app_db.count_question", new=count),
        patch.multiple("server.main.settings", **settings_overrides),
    ):
        return client.post("/fpl/ask", json={"question": "Should I captain Salah?"}, auth=auth)


def test_fpl_ask_allows_question_within_daily_limit() -> None:
    response = _ask_with_question_count(AsyncMock(return_value=5), daily_question_limit=5)
    assert response.status_code == 200


def test_fpl_ask_rejects_question_over_daily_limit() -> None:
    count = AsyncMock(return_value=6)
    response = _ask_with_question_count(count, daily_question_limit=5, google_client_id="")

    assert response.status_code == 429
    assert response.json()["detail"] == (
        "Daily limit reached — 5 questions per day. Resets at 00:00 UTC."
    )
    # Anonymous callers are counted by hashed IP, never the raw address.
    assert count.call_args.args[0].startswith("ip:")
    assert "testclient" not in count.call_args.args[0]


def test_fpl_ask_over_limit_suggests_sign_in_when_google_is_configured() -> None:
    response = _ask_with_question_count(
        AsyncMock(return_value=6), daily_question_limit=5, google_client_id="client-id"
    )
    assert response.status_code == 429
    assert "Sign in with Google" in response.json()["detail"]


def test_fpl_ask_daily_limit_fails_open_when_counter_errors() -> None:
    # e.g. migration 005 not applied yet — the chat must keep working.
    response = _ask_with_question_count(
        AsyncMock(side_effect=RuntimeError("relation does not exist")), daily_question_limit=5
    )
    assert response.status_code == 200
    assert _parse_sse(response.text) == "Captain Salah this week."


def test_usage_key_prefers_signed_in_user() -> None:
    from unittest.mock import MagicMock

    from server.main import _usage_key

    request = MagicMock()
    request.session = {"user_id": 42}
    assert _usage_key(request) == "user:42"


def test_fpl_ask_admin_password_bypasses_daily_limit() -> None:
    count = AsyncMock(return_value=99)
    response = _ask_with_question_count(
        count, auth=("admin", "s3cret"), daily_question_limit=5, admin_password="s3cret"
    )
    assert response.status_code == 200
    count.assert_not_awaited()  # exempt requests are not counted at all


def test_fpl_ask_wrong_admin_password_does_not_bypass_daily_limit() -> None:
    response = _ask_with_question_count(
        AsyncMock(return_value=99),
        auth=("admin", "guess"),
        daily_question_limit=5,
        admin_password="s3cret",
    )
    assert response.status_code == 429


def test_fpl_ask_no_admin_password_configured_does_not_bypass_daily_limit() -> None:
    # /admin is open when no password is set (dev); the limit bypass must not be.
    response = _ask_with_question_count(
        AsyncMock(return_value=99), auth=("admin", ""), daily_question_limit=5, admin_password=""
    )
    assert response.status_code == 429


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session", "expected"),
    [
        ({"email": "Owner@Example.com", "email_verified": True}, True),
        ({"email": "owner@example.com", "email_verified": False}, False),
        ({"email": "someone@example.com", "email_verified": True}, False),
        ({}, False),
    ],
)
async def test_daily_limit_exemption_by_signed_in_email(session, expected) -> None:
    from unittest.mock import MagicMock

    from server.main import _is_exempt_from_daily_limit

    request = MagicMock()
    request.session = session
    request.headers = {}
    with patch.multiple(
        "server.main.settings",
        daily_limit_exempt_emails="owner@example.com, other@example.com",
        admin_password="",
    ):
        assert await _is_exempt_from_daily_limit(request) is expected


def _signed_in_client(user_id: int = 42) -> TestClient:
    signed_in = TestClient(app)
    mock_token = {"userinfo": {"sub": "google-123", "email": "p@example.com", "name": "P"}}
    with (
        patch(
            "server.main.oauth.google.authorize_access_token",
            new=AsyncMock(return_value=mock_token),
        ),
        patch("server.main.app_db.get_or_create_user", new=AsyncMock(return_value=user_id)),
        patch("server.main.app_db.merge_device_into_user", new=AsyncMock()),
    ):
        signed_in.get("/auth/google/callback", follow_redirects=False)
    return signed_in


def test_conversations_require_sign_in() -> None:
    anonymous = TestClient(app)
    with patch("server.main.app_db.list_conversations", new=AsyncMock()) as mock_list:
        assert anonymous.get("/fpl/conversations").status_code == 401
        assert anonymous.delete("/fpl/conversations/thread-1").status_code == 401
    mock_list.assert_not_awaited()


def test_conversations_lists_only_the_signed_in_users_history() -> None:
    history = [{"id": "thread-1", "created_at": 1, "updated_at": 2, "messages": []}]
    with patch(
        "server.main.app_db.list_conversations", new=AsyncMock(return_value=history)
    ) as mock_list:
        response = _signed_in_client(user_id=42).get("/fpl/conversations")

    assert response.json() == {"conversations": history}
    mock_list.assert_awaited_once_with(42)


def test_delete_conversation_is_scoped_to_the_signed_in_user() -> None:
    with patch(
        "server.main.app_db.delete_conversation", new=AsyncMock(return_value=True)
    ) as mock_delete:
        response = _signed_in_client(user_id=42).delete("/fpl/conversations/thread-1")

    assert response.json() == {"status": "ok"}
    mock_delete.assert_awaited_once_with(42, "thread-1")


def test_delete_conversation_returns_404_when_not_owned() -> None:
    with patch("server.main.app_db.delete_conversation", new=AsyncMock(return_value=False)):
        response = _signed_in_client().delete("/fpl/conversations/someone-elses")
    assert response.status_code == 404


def test_fpl_ask_skips_saving_messages_when_conversation_is_not_owned() -> None:
    # upsert_conversation returns None when the session id belongs to someone else
    with (
        patch(
            "server.main.claude_client.ask",
            new=AsyncMock(return_value=_mock_stream("Captain Salah this week.")),
        ),
        patch("server.main.app_db.upsert_conversation", new=AsyncMock(return_value=None)),
        patch("server.main.app_db.save_chat_messages", new=AsyncMock()) as mock_save,
    ):
        response = client.post(
            "/fpl/ask", json={"question": "Should I captain Salah?", "session_id": "not-mine"}
        )

    assert response.status_code == 200
    mock_save.assert_not_awaited()


def test_group_conversation_rows_folds_messages_into_threads() -> None:
    from datetime import UTC, datetime

    from server.app_db import group_conversation_rows

    t = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    ms = int(t.timestamp() * 1000)

    def row(session, message_id, role, content):
        return {
            "client_session_id": session,
            "created_at": t,
            "updated_at": t,
            "message_id": message_id,
            "role": role,
            "content": content,
            "message_created_at": t,
        }

    grouped = group_conversation_rows(
        [
            row("thread-b", 3, "user", "Captain?"),
            row("thread-b", 4, "assistant", "Salah."),
            row("thread-a", 1, "user", "Wildcard?"),
        ]
    )

    assert [c["id"] for c in grouped] == ["thread-b", "thread-a"]  # query order preserved
    assert grouped[0] == {
        "id": "thread-b",
        "created_at": ms,
        "updated_at": ms,
        "messages": [
            {"id": "srv-3", "role": "user", "content": "Captain?", "created_at": ms},
            {"id": "srv-4", "role": "assistant", "content": "Salah.", "created_at": ms},
        ],
    }
    assert len(grouped[1]["messages"]) == 1
