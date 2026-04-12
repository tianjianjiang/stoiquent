from __future__ import annotations

import click


@click.group()
def main() -> None:
    """Stoiquent - Local LLM agent with agentskills.io skills."""


@main.command()
@click.option(
    "--mode",
    default=None,
    type=click.Choice(["native", "browser"]),
    help="UI mode (overrides config)",
)
def run(mode: str | None) -> None:
    """Launch the NiceGUI desktop app."""
    from stoiquent.config import load_config

    config = load_config()
    if mode is not None:
        config.ui.mode = mode  # type: ignore[assignment]

    from stoiquent.app import start

    start(config)


@main.command()
def serve() -> None:
    """Start as MCP server for external clients."""
    click.echo("Not implemented yet (Phase 3)")


@main.command(name="list-skills")
def list_skills() -> None:
    """List all discovered skills."""
    click.echo("Not implemented yet (Phase 2)")
