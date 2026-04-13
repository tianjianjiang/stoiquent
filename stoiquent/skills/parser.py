from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from stoiquent.skills.models import SkillMeta

logger = logging.getLogger(__name__)

_FRONTMATTER_FENCE = "---"


def parse_skill_md(path: Path) -> tuple[SkillMeta, str] | None:
    """Parse a SKILL.md file into metadata and instruction body.

    Returns (SkillMeta, instructions) or None if the file is unparseable
    or missing required fields (name/description).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Cannot read %s: %s", path, e)
        return None

    frontmatter_raw, body = _split_frontmatter(text)
    if frontmatter_raw is None:
        logger.warning("No YAML frontmatter found in %s", path)
        return None

    try:
        data = yaml.safe_load(frontmatter_raw)
    except yaml.YAMLError as e:
        logger.warning("Invalid YAML in %s: %s", path, e)
        return None

    if not isinstance(data, dict):
        logger.warning("YAML frontmatter is not a mapping in %s", path)
        return None

    try:
        meta = SkillMeta(**data)
    except ValidationError as e:
        logger.warning("Invalid skill metadata in %s: %s", path, e)
        return None

    return meta, body.strip()


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split text at --- fences into (frontmatter, body).

    Returns (None, full_text) if no valid fences found.
    """
    stripped = text.strip()
    if not stripped.startswith(_FRONTMATTER_FENCE):
        return None, text

    after_first = stripped[len(_FRONTMATTER_FENCE) :]
    end_idx = after_first.find(f"\n{_FRONTMATTER_FENCE}")
    if end_idx == -1:
        return None, text

    frontmatter = after_first[:end_idx].strip()
    body_start = end_idx + len(f"\n{_FRONTMATTER_FENCE}")
    body = after_first[body_start:]

    return frontmatter, body
