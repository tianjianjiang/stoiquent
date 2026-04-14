from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import ProviderConfig

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:0.6b"


def _ollama_available() -> bool:
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _model_available() -> bool:
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3.0)
        models = resp.json().get("models", [])
        return any(m.get("name", "").startswith(OLLAMA_MODEL) for m in models)
    except (httpx.HTTPError, ValueError):
        return False


skip_no_ollama = pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama is not running at localhost:11434",
)

skip_no_model = pytest.mark.skipif(
    not _model_available(),
    reason=f"Model {OLLAMA_MODEL} not available in Ollama",
)


@pytest.fixture
def provider_config() -> ProviderConfig:
    return ProviderConfig(
        base_url=f"{OLLAMA_BASE_URL}/v1",
        model=OLLAMA_MODEL,
        supports_reasoning=True,
        native_tools=True,
    )


@pytest_asyncio.fixture
async def provider(
    provider_config: ProviderConfig,
) -> AsyncIterator[OpenAICompatProvider]:
    p = OpenAICompatProvider(provider_config)
    try:
        yield p
    finally:
        await p.close()
