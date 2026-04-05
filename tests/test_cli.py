import httpx
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def test_health_success(respx_mock):
    respx_mock.get("http://localhost:8000/health").mock(
        return_value=httpx.Response(200, json={"status": "ok", "environment": "development"})
    )
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 0
    assert "ok" in result.output


def test_health_server_unreachable(respx_mock):
    respx_mock.get("http://localhost:8000/health").mock(side_effect=httpx.ConnectError("refused"))
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 1
    assert "Could not connect" in result.output


def test_ask_success(respx_mock):
    respx_mock.post("http://localhost:8000/fpl/ask").mock(
        return_value=httpx.Response(
            200, json={"answer": "Captain Salah this week.", "league": "fpl"}
        )
    )
    result = runner.invoke(app, ["ask", "Should I captain Salah?"])
    assert result.exit_code == 0
    assert "Captain Salah this week." in result.output


def test_ask_server_unreachable(respx_mock):
    respx_mock.post("http://localhost:8000/fpl/ask").mock(side_effect=httpx.ConnectError("refused"))
    result = runner.invoke(app, ["ask", "Should I captain Salah?"])
    assert result.exit_code == 1
    assert "Could not connect" in result.output


def test_ask_server_error(respx_mock):
    respx_mock.post("http://localhost:8000/fpl/ask").mock(return_value=httpx.Response(500))
    result = runner.invoke(app, ["ask", "Should I captain Salah?"])
    assert result.exit_code == 1
    assert "500" in result.output


def test_ask_custom_league(respx_mock):
    respx_mock.post("http://localhost:8000/worldcup/ask").mock(
        return_value=httpx.Response(200, json={"answer": "Pick Mbappe.", "league": "worldcup"})
    )
    result = runner.invoke(app, ["ask", "Who should I pick?", "--league", "worldcup"])
    assert result.exit_code == 0
    assert "Pick Mbappe." in result.output
