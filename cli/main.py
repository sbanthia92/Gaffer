"""
The Gaffer CLI — invoked as `gaffer`.

Expects the API server to be running at SERVER_URL (default: http://localhost:8000).
Set SERVER_URL in .env to point at a remote server when deployed.
"""

import httpx
import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner

app = typer.Typer(
    name="gaffer",
    help="The Gaffer — AI-powered football analyst.",
    no_args_is_help=True,
)
console = Console()

_DEFAULT_SERVER = "http://localhost:8000"


def _server_url() -> str:
    import os

    return os.environ.get("SERVER_URL", _DEFAULT_SERVER)


@app.command()
def ask(
    question: str = typer.Argument(..., help="Your question, e.g. 'Should I captain Salah?'"),
    league: str = typer.Option("fpl", "--league", "-l", help="League context: fpl"),
) -> None:
    """Ask The Gaffer a question about your fantasy team."""
    with Live(Spinner("dots", text="[cyan]Thinking...[/cyan]"), console=console, transient=True):
        try:
            response = httpx.post(
                f"{_server_url()}/{league}/ask",
                json={"question": question},
                timeout=60.0,
            )
            response.raise_for_status()
        except httpx.ConnectError:
            console.print(
                Panel(
                    f"[red]Could not connect to the server at {_server_url()}.\n"
                    "Make sure it's running: [bold]uvicorn server.main:app --reload[/bold][/red]",
                    title="Connection Error",
                    border_style="red",
                )
            )
            raise typer.Exit(code=1)
        except httpx.HTTPStatusError as e:
            console.print(
                Panel(
                    f"[red]Server returned an error: {e.response.status_code}[/red]",
                    title="Error",
                    border_style="red",
                )
            )
            raise typer.Exit(code=1)

    data = response.json()
    answer = data.get("answer", "")
    console.print(
        Panel(
            Markdown(answer),
            title=f"[bold green]The Gaffer[/bold green] · {league.upper()}",
            border_style="green",
            padding=(1, 2),
        )
    )


@app.command()
def health(
    league: str = typer.Option("fpl", "--league", "-l", help="League context: fpl"),
) -> None:
    """Check if the API server is running."""
    try:
        response = httpx.get(f"{_server_url()}/health", timeout=5.0)
        response.raise_for_status()
        data = response.json()
        console.print(
            Panel(
                f"[green]status:[/green] {data.get('status')}\n"
                f"[green]environment:[/green] {data.get('environment')}",
                title="[bold green]Server Health[/bold green]",
                border_style="green",
            )
        )
    except httpx.ConnectError:
        console.print(
            Panel(
                f"[red]Could not connect to {_server_url()}[/red]",
                title="Server Unreachable",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)


def main() -> None:
    app()
