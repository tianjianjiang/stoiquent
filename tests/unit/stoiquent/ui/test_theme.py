from __future__ import annotations

import pytest
from nicegui import ui
from nicegui.testing import User

from stoiquent.ui.theme import DarkModeToggle, apply_theme


@pytest.mark.asyncio
async def test_apply_theme_injects_css_variables(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """apply_theme must call ui.add_head_html with our CSS custom properties."""
    captured: list[str] = []
    real_add_head_html = ui.add_head_html

    def recording(html: str) -> None:
        captured.append(html)
        real_add_head_html(html)

    monkeypatch.setattr("stoiquent.ui.theme.ui.add_head_html", recording)

    @ui.page("/test-theme-css")
    async def page() -> None:
        apply_theme()

    await user.open("/test-theme-css")

    joined = "\n".join(captured)
    assert "--sq-bg: #171614" in joined  # dark primary background
    assert "--sq-fg: #F9F6EF" in joined  # dark foreground
    assert "--sq-accent: #E8946A" in joined  # dark coral accent
    assert "body.body--dark" in joined  # quasar dark-mode selector
    assert ".sq-msg" in joined  # flat message class
    assert ".sq-tool-icon" in joined  # tool card token


@pytest.mark.asyncio
async def test_apply_theme_injects_google_fonts_link(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """apply_theme must inject the Google Fonts stylesheet link."""
    captured: list[str] = []
    monkeypatch.setattr(
        "stoiquent.ui.theme.ui.add_head_html",
        lambda html: captured.append(html),
    )

    @ui.page("/test-theme-fonts")
    async def page() -> None:
        apply_theme()

    await user.open("/test-theme-fonts")

    joined = "\n".join(captured)
    assert "fonts.googleapis.com" in joined
    assert "Inter" in joined
    assert "Source+Serif+4" in joined
    assert "JetBrains+Mono" in joined


@pytest.mark.asyncio
async def test_dark_mode_toggle_defaults_to_dark(user: User) -> None:
    """Default construction should enable dark mode."""
    toggle: DarkModeToggle | None = None

    @ui.page("/test-toggle-default")
    async def page() -> None:
        nonlocal toggle
        toggle = DarkModeToggle()

    await user.open("/test-toggle-default")
    assert toggle is not None
    assert toggle.value is True


@pytest.mark.asyncio
async def test_dark_mode_toggle_flips_on_toggle(user: User) -> None:
    """toggle() must flip the ui.dark_mode() value."""
    toggle: DarkModeToggle | None = None

    @ui.page("/test-toggle-flip")
    async def page() -> None:
        nonlocal toggle
        toggle = DarkModeToggle()

    await user.open("/test-toggle-flip")
    assert toggle is not None
    initial = toggle.value
    toggle.toggle()
    assert toggle.value is not initial
    toggle.toggle()
    assert toggle.value is initial


@pytest.mark.asyncio
async def test_dark_mode_toggle_explicit_light_default(user: User) -> None:
    """default_dark=False must start in light mode."""
    toggle: DarkModeToggle | None = None

    @ui.page("/test-toggle-light")
    async def page() -> None:
        nonlocal toggle
        toggle = DarkModeToggle(default_dark=False)

    await user.open("/test-toggle-light")
    assert toggle is not None
    assert toggle.value is False


@pytest.mark.asyncio
async def test_dark_mode_toggle_persists_on_change(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Value changes must write the new state to localStorage via JS."""
    js_calls: list[str] = []
    monkeypatch.setattr(
        "stoiquent.ui.theme.ui.run_javascript",
        lambda code: js_calls.append(code),
    )

    toggle: DarkModeToggle | None = None

    @ui.page("/test-toggle-persist")
    async def page() -> None:
        nonlocal toggle
        toggle = DarkModeToggle()

    await user.open("/test-toggle-persist")
    assert toggle is not None
    js_calls.clear()  # drop any setup calls (e.g. restore)
    toggle.toggle()

    assert any(
        "localStorage.setItem" in c and "stoiquent:dark_mode" in c for c in js_calls
    ), f"Expected localStorage.setItem call; got: {js_calls}"


@pytest.mark.asyncio
async def test_dark_mode_toggle_button_registers_mark(user: User) -> None:
    """The toggle button must be findable via its dark-mode-toggle mark."""

    @ui.page("/test-toggle-mark")
    async def page() -> None:
        DarkModeToggle()

    await user.open("/test-toggle-mark")
    # `should_see` with a mark selector confirms the button exists in the DOM.
    user.find(marker="dark-mode-toggle")
