from __future__ import annotations

import logging

import pytest
from nicegui import ui
from nicegui.testing import User

from stoiquent.ui.theme import DarkModeToggle, apply_theme


@pytest.mark.asyncio
async def test_apply_theme_injects_css_variables(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
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
async def test_apply_theme_scopes_dark_overrides_under_body_dark_selector(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Light values live at ``:root`` and dark overrides only fire under
    ``body.body--dark`` — a regression that unscopes dark tokens would
    break both palettes simultaneously and is not caught by value-present
    assertions alone."""
    captured: list[str] = []
    monkeypatch.setattr(
        "stoiquent.ui.theme.ui.add_head_html",
        lambda html: captured.append(html),
    )

    @ui.page("/test-theme-scope")
    async def page() -> None:
        apply_theme()

    await user.open("/test-theme-scope")

    joined = "\n".join(captured)
    root_start = joined.find(":root {")
    root_end = joined.find("}", root_start)
    assert root_start != -1 and root_end != -1, "missing :root block"
    root_block = joined[root_start:root_end]
    assert "--sq-bg: #F4F3EE" in root_block  # light Pampas in :root
    assert "--sq-accent: #C15F3C" in root_block  # light Crail in :root

    dark_start = joined.find("body.body--dark {")
    dark_end = joined.find("}", dark_start)
    assert dark_start != -1 and dark_end != -1, "missing body.body--dark block"
    dark_block = joined[dark_start:dark_end]
    assert "--sq-bg: #171614" in dark_block  # dark override under body--dark
    assert "--sq-accent: #E8946A" in dark_block  # dark accent under body--dark


@pytest.mark.asyncio
async def test_apply_theme_injects_google_fonts_link(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    toggle: DarkModeToggle | None = None

    @ui.page("/test-toggle-light")
    async def page() -> None:
        nonlocal toggle
        toggle = DarkModeToggle(default_dark=False)

    await user.open("/test-toggle-light")
    assert toggle is not None
    assert toggle.value is False


@pytest.mark.asyncio
async def test_dark_mode_toggle_persist_writes_false_after_toggle_from_dark(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Toggling from the dark default must write ``'false'`` to localStorage
    — confirms the value direction, not just that *some* JS call fires."""
    js_calls: list[str] = []
    monkeypatch.setattr(
        "stoiquent.ui.theme.ui.run_javascript",
        lambda code: js_calls.append(code),
    )

    toggle: DarkModeToggle | None = None

    @ui.page("/test-toggle-persist-false")
    async def page() -> None:
        nonlocal toggle
        toggle = DarkModeToggle()

    await user.open("/test-toggle-persist-false")
    assert toggle is not None
    await toggle._restore()  # bind persist handler deterministically
    js_calls.clear()
    toggle.toggle()

    setitem_calls = [c for c in js_calls if "localStorage.setItem" in c]
    assert setitem_calls, f"no setItem call after toggle; got {js_calls}"
    assert '"false"' in setitem_calls[-1], setitem_calls[-1]


@pytest.mark.asyncio
async def test_dark_mode_toggle_persist_writes_true_after_toggle_from_light(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    js_calls: list[str] = []
    monkeypatch.setattr(
        "stoiquent.ui.theme.ui.run_javascript",
        lambda code: js_calls.append(code),
    )

    toggle: DarkModeToggle | None = None

    @ui.page("/test-toggle-persist-true")
    async def page() -> None:
        nonlocal toggle
        toggle = DarkModeToggle(default_dark=False)

    await user.open("/test-toggle-persist-true")
    assert toggle is not None
    await toggle._restore()
    js_calls.clear()
    toggle.toggle()

    setitem_calls = [c for c in js_calls if "localStorage.setItem" in c]
    assert setitem_calls, f"no setItem call after toggle; got {js_calls}"
    assert '"true"' in setitem_calls[-1], setitem_calls[-1]


@pytest.mark.asyncio
async def test_dark_mode_toggle_restore_applies_saved_false(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A previously saved ``'false'`` must convert the default-dark toggle
    to light on restore — the core invariant the persistence story
    promises."""

    async def fake_js(code: str) -> str | None:
        return "false" if "getItem" in code else None

    monkeypatch.setattr("stoiquent.ui.theme.ui.run_javascript", fake_js)

    toggle: DarkModeToggle | None = None

    @ui.page("/test-toggle-restore-false")
    async def page() -> None:
        nonlocal toggle
        toggle = DarkModeToggle()  # default_dark=True

    await user.open("/test-toggle-restore-false")
    assert toggle is not None
    assert toggle.value is True  # default before restore
    await toggle._restore()
    assert toggle.value is False


@pytest.mark.asyncio
async def test_dark_mode_toggle_restore_applies_saved_true(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_js(code: str) -> str | None:
        return "true" if "getItem" in code else None

    monkeypatch.setattr("stoiquent.ui.theme.ui.run_javascript", fake_js)

    toggle: DarkModeToggle | None = None

    @ui.page("/test-toggle-restore-true")
    async def page() -> None:
        nonlocal toggle
        toggle = DarkModeToggle(default_dark=False)

    await user.open("/test-toggle-restore-true")
    assert toggle is not None
    assert toggle.value is False
    await toggle._restore()
    assert toggle.value is True


@pytest.mark.asyncio
async def test_dark_mode_toggle_restore_keeps_default_when_no_value_saved(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_js(code: str) -> str | None:
        return None

    monkeypatch.setattr("stoiquent.ui.theme.ui.run_javascript", fake_js)

    toggle: DarkModeToggle | None = None

    @ui.page("/test-toggle-restore-none")
    async def page() -> None:
        nonlocal toggle
        toggle = DarkModeToggle()  # default_dark=True

    await user.open("/test-toggle-restore-none")
    assert toggle is not None
    await toggle._restore()
    assert toggle.value is True  # default preserved


@pytest.mark.asyncio
async def test_dark_mode_toggle_restore_logs_and_keeps_default_on_error(
    user: User,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A non-Cancelled exception from ``ui.run_javascript`` must surface at
    DEBUG (debuggability) while preserving the toggle default
    (resilience)."""

    async def failing_js(code: str) -> None:
        raise RuntimeError("client not connected")

    monkeypatch.setattr("stoiquent.ui.theme.ui.run_javascript", failing_js)

    toggle: DarkModeToggle | None = None

    @ui.page("/test-toggle-restore-err")
    async def page() -> None:
        nonlocal toggle
        toggle = DarkModeToggle()

    await user.open("/test-toggle-restore-err")
    assert toggle is not None
    with caplog.at_level(logging.DEBUG, logger="stoiquent.ui.theme"):
        await toggle._restore()
    assert toggle.value is True  # default preserved
    assert any("dark-mode restore skipped" in r.message for r in caplog.records), (
        f"expected DEBUG log; got {[r.message for r in caplog.records]}"
    )


@pytest.mark.asyncio
async def test_dark_mode_toggle_cancelled_error_propagates(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``asyncio.CancelledError`` must never be swallowed — tasks being
    cancelled need to unwind, not silently continue."""
    import asyncio

    async def cancelled_js(code: str) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr("stoiquent.ui.theme.ui.run_javascript", cancelled_js)

    toggle: DarkModeToggle | None = None

    @ui.page("/test-toggle-cancelled")
    async def page() -> None:
        nonlocal toggle
        toggle = DarkModeToggle()

    await user.open("/test-toggle-cancelled")
    assert toggle is not None
    with pytest.raises(asyncio.CancelledError):
        await toggle._restore()


@pytest.mark.asyncio
async def test_dark_mode_toggle_button_exposes_aria_label(user: User) -> None:
    """The icon-only toggle needs an accessible name for screen readers and
    for Lighthouse's ``button-name`` audit."""

    @ui.page("/test-toggle-aria")
    async def page() -> None:
        DarkModeToggle()

    await user.open("/test-toggle-aria")
    button = list(user.find(marker="dark-mode-toggle").elements)[0]
    props_str = str(getattr(button, "_props", {}))
    assert "Toggle dark mode" in props_str, props_str


@pytest.mark.asyncio
async def test_dark_mode_toggle_button_registers_mark(user: User) -> None:
    @ui.page("/test-toggle-mark")
    async def page() -> None:
        DarkModeToggle()

    await user.open("/test-toggle-mark")
    user.find(marker="dark-mode-toggle")
