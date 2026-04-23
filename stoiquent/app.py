from __future__ import annotations

import logging

from nicegui import app, ui

from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import AppConfig
from stoiquent.persistence import ConversationStore
from stoiquent.projects import ProjectStore
from stoiquent.sandbox.detect import detect_backend
from stoiquent.skills.active_store import ActiveSkillsLoadError, ActiveSkillsStore
from stoiquent.skills.catalog import SkillCatalog
from stoiquent.skills.controller import SkillController
from stoiquent.skills.discovery import discover_skills
from stoiquent.skills.mcp_bridge import MCPBridge
from stoiquent.ui import layout

logger = logging.getLogger(__name__)


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

    active_store = ActiveSkillsStore(config.persistence)
    controller = SkillController(catalog, mcp_bridge, active_store)

    session = Session(
        provider=provider,
        catalog=catalog,
        controller=controller,
        sandbox=sandbox,
        mcp_bridge=mcp_bridge,
        iteration_limit=config.agent.iteration_limit,
        tool_timeout=config.sandbox.tool_timeout,
    )

    store = ConversationStore(config.persistence)
    project_store = ProjectStore(config.persistence)
    try:
        store.ensure_dirs()
        project_store.ensure_dirs()
        active_store.ensure_dirs()
    except OSError as e:
        raise SystemExit(
            f"Cannot create persistence directory at "
            f"{config.persistence.data_dir}: {e}"
        ) from e

    app.on_shutdown(store.drain_pending)
    app.on_shutdown(project_store.drain_pending)
    app.on_shutdown(active_store.drain_pending)

    async def _restore_active_skills() -> None:
        try:
            names = active_store.load()
        except ActiveSkillsLoadError:
            logger.warning(
                "active_skills.json is damaged; starting with no skills active"
            )
            return
        if not names:
            return
        try:
            results = await controller.activate_many(names)
        except Exception:
            logger.exception(
                "Unhandled error restoring active skills; continuing startup"
            )
            return
        for name, result in results.items():
            if not result.success:
                logger.warning(
                    "Could not restore active skill %r: %s", name, result.reason
                )

    app.on_startup(_restore_active_skills)

    @ui.page("/")
    async def _main_page() -> None:  # pragma: no cover
        await layout.render(session, store, config, project_store=project_store)

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
