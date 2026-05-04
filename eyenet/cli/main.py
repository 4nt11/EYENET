"""EYENET CLI entrypoint. Real commands land in Milestone 1+."""

from __future__ import annotations

import typer

from eyenet import __version__

app = typer.Typer(
    name="eyenet",
    help="EYENET — Don't look. Observe.",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """Root callback — forces subcommand mode even with a single command."""


@app.command()
def version() -> None:
    """Print the EYENET version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
