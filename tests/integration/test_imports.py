from __future__ import annotations

import pytest


@pytest.mark.integration
def test_should_import_all_modules() -> None:
    """Verify all package imports resolve without errors."""
    from stoiquent.agent.context import build_messages  # noqa: F401
    from stoiquent.agent.loop import run_agent_loop  # noqa: F401
    from stoiquent.agent.session import Session  # noqa: F401
    from stoiquent.app import start  # noqa: F401
    from stoiquent.cli import main  # noqa: F401
    from stoiquent.config import load_config  # noqa: F401
    from stoiquent.llm.openai_compat import OpenAICompatProvider  # noqa: F401
    from stoiquent.llm.provider import LLMProvider  # noqa: F401
    from stoiquent.llm.reasoning import extract_reasoning  # noqa: F401
    from stoiquent.models import (  # noqa: F401
        AppConfig,
        Message,
        ProviderConfig,
        StreamChunk,
        ToolCall,
        UIConfig,
    )


@pytest.mark.integration
def test_should_verify_openai_compat_satisfies_protocol() -> None:
    """OpenAICompatProvider should satisfy the LLMProvider protocol."""
    from stoiquent.llm.openai_compat import OpenAICompatProvider
    from stoiquent.llm.provider import LLMProvider
    from stoiquent.models import ProviderConfig

    config = ProviderConfig(base_url="http://localhost:11434/v1", model="test")
    provider = OpenAICompatProvider(config)
    assert isinstance(provider, LLMProvider)
