from __future__ import annotations

import re

_THINK_PATTERN = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def extract_reasoning(content: str) -> tuple[str, str | None]:
    """Extract reasoning from content containing <think> tags.

    Returns (clean_content, reasoning_trace).
    """
    matches = _THINK_PATTERN.findall(content)
    if not matches:
        return content, None

    reasoning_parts = [m.strip() for m in matches if m.strip()]
    if not reasoning_parts:
        clean = _THINK_PATTERN.sub("", content).strip()
        return clean, None
    reasoning = "\n".join(reasoning_parts)
    clean = _THINK_PATTERN.sub("", content).strip()
    return clean, reasoning
