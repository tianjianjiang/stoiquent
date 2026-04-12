from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from stoiquent.models import Message

if TYPE_CHECKING:
    from stoiquent.llm.provider import LLMProvider


@dataclass
class Session:
    provider: LLMProvider
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    messages: list[Message] = field(default_factory=list)
