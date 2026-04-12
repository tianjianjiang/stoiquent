from __future__ import annotations

import logging

from nicegui import ui

from stoiquent.agent.loop import run_agent_loop
from stoiquent.agent.session import Session
from stoiquent.models import StreamChunk

logger = logging.getLogger(__name__)


class ChatPanel:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._messages_container: ui.column | None = None
        self._input: ui.input | None = None

    def render(self) -> None:
        with ui.column().classes("w-full flex-grow gap-0"):
            self._messages_container = ui.column().classes(
                "w-full flex-grow gap-2 p-4 overflow-auto"
            )
            with ui.row().classes("w-full p-4 gap-2 items-center border-t"):
                self._input = (
                    ui.input(placeholder="Type a message...")
                    .classes("flex-grow")
                    .on("keydown.enter", self._send)
                )
                ui.button("Send", on_click=self._send).props("flat")

    async def _send(self) -> None:
        if not self._input or not self._input.value:
            return

        user_text = self._input.value.strip()
        if not user_text:
            return

        self._input.value = ""

        if self._messages_container is None:
            raise RuntimeError("ChatPanel.render() must be called before _send()")

        with self._messages_container:
            ui.chat_message(text=user_text, name="You", sent=True)

            ui.chat_message(name="Assistant", sent=False)
            response_md = ui.markdown("")
            reasoning_expansion = ui.expansion(
                "Reasoning", icon="psychology"
            ).classes("w-full text-xs")
            with reasoning_expansion:
                reasoning_md = ui.markdown("")
            reasoning_expansion.set_visibility(False)

            spinner = ui.spinner("dots", size="sm")

        content_so_far = ""
        reasoning_so_far = ""
        has_reasoning = False

        async def on_chunk(chunk: StreamChunk) -> None:
            nonlocal content_so_far, reasoning_so_far, has_reasoning

            if chunk.content_delta:
                content_so_far += chunk.content_delta
                response_md.set_content(content_so_far)

            if chunk.reasoning_delta:
                reasoning_so_far += chunk.reasoning_delta
                if not has_reasoning:
                    has_reasoning = True
                    reasoning_expansion.set_visibility(True)
                reasoning_md.set_content(reasoning_so_far)

        try:
            await run_agent_loop(self.session, user_text, on_chunk)
        except (ConnectionError, TimeoutError) as e:
            logger.warning("LLM connection failed: %s", e)
            response_md.set_content(f"**Connection error:** {e}")
        except Exception:
            logger.exception("Unexpected error in agent loop")
            response_md.set_content(
                "**Error:** An unexpected error occurred. Check logs for details."
            )
        finally:
            self._messages_container.remove(spinner)

        ui.run_javascript("window.scrollTo(0, document.body.scrollHeight)")
