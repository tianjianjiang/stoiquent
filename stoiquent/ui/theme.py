"""Dark-first visual theme for Stoiquent.

`apply_theme()` injects fonts and the CSS-variable-driven stylesheet into
the page head. `DarkModeToggle` wraps `ui.dark_mode()` behind a header icon
button and persists the preference to `localStorage` so the mode survives
page reloads without requiring a server-side storage secret.
"""

from __future__ import annotations

import json
import logging
from typing import Final

from nicegui import ui
from nicegui.events import ValueChangeEventArguments

logger = logging.getLogger(__name__)

_FONTS_URL: Final[str] = (
    "https://fonts.googleapis.com/css2?"
    "family=Inter:wght@400;500;600&"
    "family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&"
    "family=JetBrains+Mono:wght@400;600&display=swap"
)

_CSS: Final[str] = """
:root {
  --sq-bg: #F4F3EE;
  --sq-fg: #141311;
  --sq-surface: #FFFFFF;
  --sq-border: #E4E1D9;
  --sq-muted: #6B6B63;
  --sq-accent: #C15F3C;
  --sq-accent-fg: #FFFFFF;
  --sq-code-bg: #EDEAE1;
  --sq-font-sans: "Inter", system-ui, -apple-system, sans-serif;
  --sq-font-serif: "Source Serif 4", Georgia, serif;
  --sq-font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, monospace;
  --q-primary: var(--sq-accent);
}

body.body--dark {
  --sq-bg: #171614;
  --sq-fg: #F9F6EF;
  --sq-surface: #1F1E1C;
  --sq-border: #2E2C29;
  --sq-muted: #9B958A;
  --sq-accent: #E8946A;
  --sq-accent-fg: #0F0E0C;
  --sq-code-bg: #0F0E0D;
}

html, body, .q-page, .nicegui-content {
  background-color: var(--sq-bg);
  color: var(--sq-fg);
  font-family: var(--sq-font-sans);
}

h1, h2, h3, h4, h5, h6,
.text-h1, .text-h2, .text-h3, .text-h4, .text-h5, .text-h6 {
  font-family: var(--sq-font-serif);
  letter-spacing: -0.01em;
  color: var(--sq-fg);
}

code, pre, .q-code, .nicegui-code {
  font-family: var(--sq-font-mono);
  background-color: var(--sq-code-bg);
  color: var(--sq-fg);
  border-radius: 6px;
}

/* Flat message rows, styled entirely via theme tokens. */
.sq-msg {
  width: 100%;
  padding: 12px 16px;
  border-left: 3px solid transparent;
  gap: 4px;
}
.sq-msg--user { border-left-color: var(--sq-accent); }
.sq-msg--assistant { border-left-color: var(--sq-border); }
.sq-msg__role {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--sq-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.sq-msg__body { color: var(--sq-fg); line-height: 1.6; }
.sq-msg__body a { color: var(--sq-accent); }
.sq-msg__body a:hover { text-decoration: underline; }

/* Tool card tokens. */
.sq-tool-icon { color: var(--sq-accent); }
.sq-tool-ok { color: var(--sq-accent); opacity: 0.85; }

/* Header and buttons. */
header.q-header {
  background-color: var(--sq-surface) !important;
  color: var(--sq-fg) !important;
  border-bottom: 1px solid var(--sq-border);
}
/* Remap Quasar primary utility classes to the coral accent. */
.text-primary { color: var(--sq-accent) !important; }
.bg-primary {
  background-color: var(--sq-accent) !important;
  color: var(--sq-accent-fg) !important;
}
.q-btn--flat { color: var(--sq-fg); }
.q-btn--flat .q-icon,
.q-btn--flat .text-primary,
.q-btn--flat .q-btn__content {
  color: var(--sq-accent);
}
.q-btn--flat:hover { background-color: var(--sq-border) !important; }

/* Cards (tool cards, project dialogs, etc.). */
.q-card {
  background-color: var(--sq-surface) !important;
  color: var(--sq-fg) !important;
  border: 1px solid var(--sq-border);
  box-shadow: none;
}

/* Inputs. */
.q-field__control, .q-field__native {
  color: var(--sq-fg);
}

/* Splitter separator (between sidebar and chat). */
.q-splitter__separator {
  background-color: var(--sq-border) !important;
}
"""


def apply_theme() -> None:
    ui.add_head_html('<link rel="preconnect" href="https://fonts.googleapis.com">')
    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    )
    ui.add_head_html(f'<link rel="stylesheet" href="{_FONTS_URL}">')
    ui.add_head_html(f"<style>{_CSS}</style>")


class DarkModeToggle:
    """Header-mounted icon button wrapping `ui.dark_mode()`.

    Persists the current value to browser `localStorage` under a namespaced
    key so the preference survives page reloads without a server-side
    storage secret. The persist callback is bound only after `_restore`
    finishes so an init-time value event cannot clobber the saved
    preference before we read it.
    """

    _LS_KEY: Final[str] = "stoiquent:dark_mode"

    def __init__(self, *, default_dark: bool = True) -> None:
        self._restored = False
        self._dark_mode = ui.dark_mode(value=default_dark)
        # Anchor the button element in the enclosing slot — NiceGUI
        # elements register on construction; keeping the reference
        # documents intent and prevents accidental GC.
        self._button = (
            ui.button(icon="contrast", on_click=self.toggle)
            .props('flat round dense aria-label="Toggle dark mode"')
            .tooltip("Toggle dark mode")
            .mark("dark-mode-toggle")
        )
        ui.timer(0.05, self._restore, once=True)

    @property
    def value(self) -> bool:
        return bool(self._dark_mode.value)

    def toggle(self) -> None:
        self._dark_mode.value = not self._dark_mode.value

    def _persist(self, event: ValueChangeEventArguments) -> None:
        js_value = "true" if event.value else "false"
        ui.run_javascript(
            f"localStorage.setItem({json.dumps(self._LS_KEY)}, {json.dumps(js_value)});"
        )

    async def _restore(self) -> None:
        saved: str | None = None
        try:
            saved = await ui.run_javascript(
                f"localStorage.getItem({json.dumps(self._LS_KEY)})"
            )
        except (RuntimeError, ConnectionError, TimeoutError, OSError) as exc:
            logger.debug("dark-mode restore skipped: %s", exc, exc_info=True)
        if saved is not None:
            self._dark_mode.value = str(saved).lower() == "true"
        if not self._restored:
            self._dark_mode.on_value_change(self._persist)
            self._restored = True
