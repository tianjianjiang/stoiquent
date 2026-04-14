from __future__ import annotations

import click

from stoiquent.models import UIConfig


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
        config.ui = UIConfig(mode=mode, host=config.ui.host, port=config.ui.port)

    from stoiquent.app import start

    start(config)


@main.command()
@click.option(
    "--skills-dir",
    default=None,
    type=click.Path(exists=True),
    help="Additional skills directory to discover",
)
def serve(skills_dir: str | None) -> None:
    """Start as MCP server exposing active skills as tools."""
    from stoiquent.config import load_config
    from stoiquent.skills.mcp_server import create_mcp_server

    config = load_config()
    mcp = create_mcp_server(config, skills_dir=skills_dir)
    mcp.run(transport="stdio")


@main.command(name="list-skills")
def list_skills() -> None:
    """List all discovered skills."""
    from stoiquent.config import load_config
    from stoiquent.skills.discovery import discover_skills

    config = load_config()
    skills = discover_skills(config.skills)
    if not skills:
        click.echo("No skills found.")
        return
    for name, skill in sorted(skills.items()):
        click.echo(f"  {name}: {skill.meta.description} [{skill.source}]")
