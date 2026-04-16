# Playwright MCP E2E Verification Protocol

Real-browser testing using the Playwright MCP plugin in Claude Code.
Covers gaps that NiceGUI's `User` fixture cannot: CSS rendering, Quasar
component behavior, keyboard interactions, visual layout, responsive design.

## Prerequisites

1. Start the test server (uses FakeProvider, no Ollama needed):
   ```bash
   uv run python tests/e2e/serve_for_playwright.py
   ```
2. Confirm output: `NiceGUI ready to go on http://127.0.0.1:8080`
3. Claude Code session with Playwright MCP plugin available

## Quick Smoke Test (~60 seconds)

Minimal verification that the app renders and responds.

| # | Action | MCP Tool | Parameters | Expected |
|---|--------|----------|------------|----------|
| 1 | Open app | `browser_navigate` | url: `http://127.0.0.1:8080` | Page loads |
| 2 | Wait for ready | `browser_wait_for` | text: "Stoiquent" | Header visible |
| 3 | Verify structure | `browser_snapshot` | | Contains: "Stoiquent", "New Chat", "Sessions", "Skills", "Type a message...", "Send", "Local LLM Agent" |
| 4 | Send message | `browser_click` on input, `browser_type` text: "Hello", `browser_press_key` key: "Enter" | | Message sent |
| 5 | Verify response | `browser_snapshot` | | Contains: "Hello" (user message) and "This is a test response from FakeProvider." (assistant response) |

## Full Test Suites

### Suite 1: Layout and Rendering

Verifies header, sidebar, splitter, and Quasar component rendering.

| # | Action | MCP Tool | Expected |
|---|--------|----------|----------|
| 1.1 | Navigate to app | `browser_navigate` url: `http://127.0.0.1:8080` | Page loads |
| 1.2 | Wait for ready | `browser_wait_for` text: "Stoiquent" | Header visible |
| 1.3 | Full page screenshot | `browser_take_screenshot` | Visual baseline: blue header, sidebar on left, chat area on right |
| 1.4 | Verify accessibility tree | `browser_snapshot` | Contains all key elements (header, sidebar tabs, chat input, send button) |
| 1.5 | Check header background | `browser_evaluate` js: `getComputedStyle(document.querySelector('.q-header')).backgroundColor` | Returns a blue-toned RGB value |
| 1.6 | Check splitter exists | `browser_evaluate` js: `document.querySelector('.q-splitter') !== null` | Returns `true` |

### Suite 2: Tab Navigation

Verifies Sessions and Skills tab switching in the sidebar.

| # | Action | MCP Tool | Expected |
|---|--------|----------|----------|
| 2.1 | Verify Sessions tab active | `browser_snapshot` | Shows "New Chat" button |
| 2.2 | Click Skills tab | `browser_click` text: "Skills" | Tab switches |
| 2.3 | Verify Skills content | `browser_snapshot` | Shows "No skills configured" |
| 2.4 | Click Sessions tab | `browser_click` text: "Sessions" | Tab switches back |
| 2.5 | Verify Sessions content | `browser_snapshot` | Shows "New Chat" button again |

### Suite 3: Chat Input and Keyboard

Verifies typing, Enter-to-send, and input clearing.

| # | Action | MCP Tool | Expected |
|---|--------|----------|----------|
| 3.1 | Click input field | `browser_click` placeholder: "Type a message..." | Input focused |
| 3.2 | Type a message | `browser_type` text: "Testing keyboard input" | Text appears in input |
| 3.3 | Press Enter to send | `browser_press_key` key: "Enter" | Message sent |
| 3.4 | Verify message sent | `browser_snapshot` | "Testing keyboard input" appears as user message |
| 3.5 | Verify response | `browser_wait_for` text: "This is a test response" | FakeProvider response appears |
| 3.6 | Verify input cleared | `browser_snapshot` | Input field is empty |
| 3.7 | Click Send button | `browser_click` on input, `browser_type` text: "Button test", `browser_click` text: "Send" | Message sent via button |
| 3.8 | Verify button send | `browser_snapshot` | "Button test" appears as user message |

### Suite 4: Visual Appearance

Captures visual state for review.

| # | Action | MCP Tool | Expected |
|---|--------|----------|----------|
| 4.1 | Full page screenshot | `browser_take_screenshot` | Clean layout, readable fonts, proper spacing |
| 4.2 | Check font family | `browser_evaluate` js: `getComputedStyle(document.body).fontFamily` | Contains a sans-serif font |
| 4.3 | Check body background | `browser_evaluate` js: `getComputedStyle(document.body).backgroundColor` | White or light color |

### Suite 5: Responsive Design

Verifies layout at mobile and desktop sizes.

| # | Action | MCP Tool | Expected |
|---|--------|----------|----------|
| 5.1 | Resize to mobile | `browser_resize` width: 375, height: 812 | No crash |
| 5.2 | Mobile screenshot | `browser_take_screenshot` | Layout adapts (sidebar may collapse or stack) |
| 5.3 | Mobile snapshot | `browser_snapshot` | All key elements still accessible |
| 5.4 | Resize to desktop | `browser_resize` width: 1280, height: 800 | Layout restored |
| 5.5 | Desktop screenshot | `browser_take_screenshot` | Sidebar and chat side by side |

### Suite 6: Console Errors

Verifies no JavaScript errors during interaction.

| # | Action | MCP Tool | Expected |
|---|--------|----------|----------|
| 6.1 | Check console messages | `browser_console_messages` | No error-level messages (warnings acceptable) |

## Element Targeting Strategy

- **Prefer `browser_snapshot`** (accessibility tree) over CSS selectors for assertions
- **Use text/role selectors** for `browser_click`: text "Send", text "New Chat", text "Sessions", text "Skills"
- **NiceGUI markers** appear as `data-test` attributes: `chat-input`, `send-btn`, `skills-tab`, `sessions-tab`, `new-chat-btn`, `provider-select`
- **CSS selector syntax** for markers: `[data-test="chat-input"]`
- Quasar wraps elements in additional containers -- accessibility tree is more reliable than DOM structure

## Cleanup

After testing:
```
browser_close
```
Then stop the test server (Ctrl+C in the terminal running `serve_for_playwright.py`).
