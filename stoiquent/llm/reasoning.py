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

    reasoning = "\n".join(m.strip() for m in matches)
    clean = _THINK_PATTERN.sub("", content).strip()
    return clean, reasoning
