from __future__ import annotations

import logging
from typing import Any

from stoiquent.skills.models import Skill

logger = logging.getLogger(__name__)


class SkillCatalog:
    def __init__(self, skills: dict[str, Skill] | None = None) -> None:
        self._skills: dict[str, Skill] = dict(skills) if skills else {}

    @property
    def skills(self) -> dict[str, Skill]:
        return self._skills

    def replace(self, skills: dict[str, Skill]) -> None:
        """Swap the catalog contents. Callers must pre-compute each skill's
        ``active`` flag; the catalog doesn't preserve state across replace."""
        self._skills = dict(skills)

    def activate(self, name: str) -> bool:
        skill = self._skills.get(name)
        if skill is None:
            logger.warning("Cannot activate unknown skill: %s", name)
            return False
        if skill.active:
            return True
        self._skills[name] = skill.model_copy(update={"active": True})
        logger.info("Activated skill: %s", name)
        return True

    def deactivate(self, name: str) -> bool:
        skill = self._skills.get(name)
        if skill is None:
            logger.warning("Cannot deactivate unknown skill: %s", name)
            return False
        if not skill.active:
            return True
        self._skills[name] = skill.model_copy(update={"active": False})
        logger.info("Deactivated skill: %s", name)
        return True

    def get_active_skills(self) -> list[Skill]:
        return [s for s in self._skills.values() if s.active]

    def get_catalog_prompt(self) -> str:
        if not self._skills:
            return ""
        lines = ["Available skills:"]
        for name, skill in self._skills.items():
            status = "active" if skill.active else "available"
            lines.append(f"- {name}: {skill.meta.description} [{status}]")
        return "\n".join(lines)

    def get_active_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for skill in self.get_active_skills():
            for tool_def in skill.meta.tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool_def.name,
                        "description": tool_def.description,
                        "parameters": tool_def.parameters or {
                            "type": "object",
                            "properties": {},
                        },
                    },
                })
        return tools

    def get_active_instructions(self) -> str:
        parts = []
        for skill in self.get_active_skills():
            if skill.instructions:
                parts.append(f"## Skill: {skill.meta.name}\n{skill.instructions}")
        return "\n\n".join(parts)
