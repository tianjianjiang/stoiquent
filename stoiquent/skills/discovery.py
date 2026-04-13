from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from stoiquent.models import SkillsConfig
from stoiquent.skills.models import Skill
from stoiquent.skills.parser import parse_skill_md

logger = logging.getLogger(__name__)


def discover_skills(config: SkillsConfig) -> dict[str, Skill]:
    """Discover skills from all configured paths.

    Priority: project-level > user-level > config paths.
    First discovery wins on name collision.
    """
    skills: dict[str, Skill] = {}

    project_paths = [
        Path(".agents/skills"),
        Path(".stoiquent/skills"),
    ]
    for path in project_paths:
        _scan_directory(path, "project", skills)

    for raw_path in config.paths:
        expanded = Path(raw_path).expanduser()
        _scan_directory(expanded, "config", skills)

    return skills


def _scan_directory(
    base: Path,
    source: Literal["user", "project", "config"],
    skills: dict[str, Skill],
) -> None:
    if not base.is_dir():
        return

    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue

        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue

        name = child.name
        if name in skills:
            logger.debug(
                "Skill '%s' from %s/%s skipped: already discovered from %s",
                name,
                source,
                child,
                skills[name].path,
            )
            continue

        result = parse_skill_md(skill_md)
        if result is None:
            continue

        meta, instructions = result
        skills[name] = Skill(
            meta=meta,
            path=child,
            instructions=instructions,
            source=source,
        )
        logger.info("Discovered skill '%s' from %s", name, child)
