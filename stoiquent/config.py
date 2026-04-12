from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

from stoiquent.models import AppConfig, ProviderConfig, UIConfig

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _interpolate_env(value: str) -> str:
    def replace(match: re.Match) -> str:
        return os.environ.get(match.group(1), "")
    return _ENV_VAR_PATTERN.sub(replace, value)


def _find_config_file() -> Path | None:
    candidates = [
        Path("stoiquent.toml"),
        Path.home() / ".stoiquent" / "config.toml",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or _find_config_file()
    if config_path is None:
        return AppConfig()

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    ui_config = UIConfig(**raw.get("ui", {}))

    providers: dict[str, ProviderConfig] = {}
    llm_section = raw.get("llm", {})
    default_provider = llm_section.get("default", "local-qwen")

    for name, prov_data in llm_section.get("providers", {}).items():
        if "api_key" in prov_data:
            prov_data["api_key"] = _interpolate_env(prov_data["api_key"])
        providers[name] = ProviderConfig(**prov_data)

    return AppConfig(
        ui=ui_config,
        default_provider=default_provider,
        providers=providers,
    )
