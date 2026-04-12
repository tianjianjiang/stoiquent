from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from stoiquent.llm.openai_compat import OpenAICompatProvider
from stoiquent.models import Message


@dataclass
class Session:
    provider: OpenAICompatProvider
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    messages: list[Message] = field(default_factory=list)
