from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nicegui import ui

from stoiquent.agent.loop import run_agent_loop
from stoiquent.agent.session import Session
from stoiquent.models import StreamChunk
from stoiquent.ui.tool_card import render_tool_call, render_tool_result

if TYPE_CHECKING:
    from stoiquent.persistence import ConversationStore

logger = logging.getLogger(__name__)


class ChatPanel:
    def __init__(
        self, session: Session, store: ConversationStore | None = None
    ) -> None:
        self.session = session
        self._store = store
        self._messages_container: ui.column | None = None
        self._input: ui.input | None = None
        self._sending: bool = False

    def render(self) -> None:
        with ui.column().classes("w-full flex-grow gap-0"):
            self._messages_container = (
                ui.column()
                .classes("w-full flex-grow gap-2 p-4 overflow-auto")
                .mark("messages")
            )
            with (
                ui.row()
                .classes("w-full p-4 gap-2 items-center border-t")
                .style("border-color: var(--sq-border)")
            ):
                self._input = (
                    ui.input(placeholder="Type a message...")
                    .classes("flex-grow")
                    .on("keydown.enter", self._send)
                    .mark("chat-input")
                )
                ui.button("Send", on_click=self._send).props("flat").mark("send-btn")

    def reload_messages(self) -> None:
        """Re-render the chat history from session.messages."""
        if self._messages_container is None:
            return
        self._messages_container.clear()
        with self._messages_container:
            for msg in self.session.messages:
                if msg.role == "user":
                    with _row("user", "You"):
                        ui.markdown(msg.content or "")
                elif msg.role == "assistant":
                    with _row("assistant", "Assistant"):
                        if msg.tool_calls:
                            for tc in msg.tool_calls:
                                render_tool_call(tc)
                        if msg.content:
                            ui.markdown(msg.content)
                        if msg.reasoning:
                            with ui.expansion("Reasoning", icon="psychology").classes(
                                "text-xs"
                            ):
                                ui.markdown(msg.reasoning)
                elif msg.role == "tool":
                    render_tool_result(msg.tool_call_id or "", msg.content or "")

    async def _send(self) -> None:
        if self._sending:
            return
        if not self._input or not self._input.value:
            return

        user_text = self._input.value.strip()
        if not user_text:
            return

        self._input.value = ""
        self._sending = True

        if self._messages_container is None:
            raise RuntimeError("ChatPanel.render() must be called before _send()")

        with self._messages_container:
            with _row("user", "You"):
                ui.markdown(user_text)

            assistant_body = _row("assistant", "Assistant")
            with assistant_body:
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

            if chunk.tool_call_start:
                with self._messages_container:
                    render_tool_call(chunk.tool_call_start)

            if chunk.tool_call_result:
                with self._messages_container:
                    render_tool_result(
                        chunk.tool_call_result.tool_call_id,
                        chunk.tool_call_result.content,
                    )

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
            self._sending = False
            spinner.set_visibility(False)

        if self._store is not None:
            try:
                self._store.save_background(
                    self.session.id,
                    self.session.messages,
                    self.session.project_id,
                )
            except Exception:
                logger.warning("Failed to schedule background save", exc_info=True)

        ui.run_javascript("window.scrollTo(0, document.body.scrollHeight)")


def _row(role: str, name: str) -> ui.column:
    """Return the body column of a flat ``sq-msg`` row.

    The flat layout is theme-owned — callers nest content into the returned
    body column so CSS tokens (not a Quasar chat-bubble component) drive the
    look, and so role-specific accents live in ``theme.py`` rather than in
    the chat renderer.
    """
    wrapper = ui.column().classes(f"sq-msg sq-msg--{role} w-full").mark(f"msg-{role}")
    with wrapper:
        ui.label(name).classes("sq-msg__role")
        body = ui.column().classes("sq-msg__body w-full")
    return body
