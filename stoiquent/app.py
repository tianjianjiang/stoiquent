from __future__ import annotations

from nicegui import ui

from stoiquent.agent.session import Session
from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import AppConfig
from stoiquent.ui import layout


def start(config: AppConfig) -> None:
    provider_name = config.default_provider
    provider_config = config.providers.get(provider_name)
    if provider_config is None:
        msg = f"Provider '{provider_name}' not found in config. Available: {list(config.providers)}"
        raise SystemExit(msg)

    provider = OpenAICompatProvider(provider_config)
    session = Session(provider=provider)

    @ui.page("/")
    async def main_page() -> None:
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
