from __future__ import annotations

from nicegui import app, ui

from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import AppConfig
from stoiquent.sandbox.detect import detect_backend
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.discovery import discover_skills
from stoiquent.skills.mcp_bridge import MCPBridge
from stoiquent.ui import layout


def start(config: AppConfig) -> None:
    provider_name = config.default_provider
    provider_config = config.providers.get(provider_name)
    if provider_config is None:
        available = list(config.providers) if config.providers else []
        msg = (
            f"Provider '{provider_name}' not found in config. "
            f"Available: {available}. "
            "Check stoiquent.toml or create ~/.stoiquent/config.toml"
        )
        raise SystemExit(msg)

    provider = OpenAICompatProvider(provider_config)
    app.on_shutdown(provider.close)

    catalog = SkillCatalog(discover_skills(config.skills))
    sandbox = detect_backend(config.sandbox)
    mcp_bridge = MCPBridge()
    app.on_shutdown(mcp_bridge.stop_all)

    session = Session(
        provider=provider,
        catalog=catalog,
        sandbox=sandbox,
        mcp_bridge=mcp_bridge,
        iteration_limit=config.agent.iteration_limit,
        tool_timeout=config.sandbox.tool_timeout,
    )

    @ui.page("/")
    async def _main_page() -> None:  # pragma: no cover
        layout.render(session)

    kwargs: dict = {
        "title": "Stoiquent",
        "reload": False,
    }

    if config.ui.mode == "native":
        kwargs["native"] = True
        kwargs["window_size"] = (1200, 800)
    else:
        kwargs["host"] = config.ui.host
        kwargs["port"] = config.ui.port

    ui.run(**kwargs)
