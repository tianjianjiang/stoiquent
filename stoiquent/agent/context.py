from __future__ import annotations

from stoiquent.agent.session import Session
from stoiquent.models import Message

BASE_SYSTEM_PROMPT = """\
You are Stoiquent, a helpful AI assistant running locally. \
You answer questions clearly and concisely. \
When reasoning through a problem, think step by step."""


def build_messages(session: Session) -> list[Message]:
    system_msg = Message(role="system", content=BASE_SYSTEM_PROMPT)
    return [system_msg, *session.messages]
