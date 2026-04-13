from __future__ import annotations

import logging
import os
import re
import tomllib
from pathlib import Path

from stoiquent.models import (
    AgentConfig,
    AppConfig,
    PersistenceConfig,
    ProviderConfig,
    SandboxConfig,
    SkillsConfig,
    UIConfig,
)

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _interpolate_env(value: str) -> str:
    def replace(match: re.Match) -> str:
        var_name = match.group(1)
        result = os.environ.get(var_name)
        if result is None:
            logger.warning(
                "Environment variable '%s' referenced in config but not set; "
                "using empty string",
                var_name,
            )
            return ""
        return result
    return _ENV_VAR_PATTERN.sub(replace, value)


def _interpolate_dict(data: dict) -> dict:
    for key, value in data.items():
        if isinstance(value, str) and "${" in value:
            data[key] = _interpolate_env(value)
    return data


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

    try:
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        raise SystemExit(f"Config file not found: {config_path}") from None
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"Invalid TOML in {config_path}: {e}") from None
    except PermissionError:
        raise SystemExit(f"Cannot read config file: {config_path}") from None

    ui_config = UIConfig(**raw.get("ui", {}))

    providers: dict[str, ProviderConfig] = {}
    llm_section = raw.get("llm", {})
    default_provider = llm_section.get("default", "local-qwen")

    for name, prov_data in llm_section.get("providers", {}).items():
        _interpolate_dict(prov_data)
        providers[name] = ProviderConfig(**prov_data)

    skills_config = SkillsConfig(**raw.get("skills", {}))
    sandbox_config = SandboxConfig(**raw.get("sandbox", {}))
    persistence_config = PersistenceConfig(**raw.get("persistence", {}))
    agent_config = AgentConfig(**raw.get("agent", {}))

    return AppConfig(
        ui=ui_config,
        default_provider=default_provider,
        providers=providers,
        skills=skills_config,
        sandbox=sandbox_config,
        persistence=persistence_config,
        agent=agent_config,
    )
