# Stoiquent

A personal desktop app for autonomous task execution using local reasoning LLMs via Ollama or any OpenAI-compatible endpoint. Skills-first: zero built-in tools, all capabilities from [agentskills.io](https://agentskills.io/specification)-compliant SKILL.md files.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A container runtime for sandboxed tool execution (see below)

## Installation

```bash
git clone https://github.com/tianjianjiang/stoiquent.git
cd stoiquent
uv sync
```

## Sandbox Setup

Stoiquent sandboxes all tool execution in containers. Auto-detection probes backends in order of isolation strength.

### macOS (Apple Silicon)

**Option 1: Apple Containers (recommended, VM-level isolation)**

Requires macOS 26 (Tahoe) or later.

```bash
# Install via MacPorts
sudo port install container

# Start the system service (downloads Kata kernel on first run)
container system start

# Verify
container run --rm alpine:latest echo "hello"
```

**Option 2: Docker via Rancher Desktop**

```bash
brew install --cask rancher
# Start Rancher Desktop, then verify:
docker run --rm alpine:latest echo "hello"
```

### Linux

Install one of: [Podman](https://podman.io/), [Finch](https://github.com/runfinch/finch), or Docker.

## Usage

```bash
# Launch desktop app
uv run stoiquent run

# Start as MCP server
uv run stoiquent serve

# List discovered skills
uv run stoiquent list-skills
```

## Configuration

Create `stoiquent.toml` in the project root or `~/.stoiquent/config.toml`:

```toml
[ui]
mode = "native"  # "native" (pywebview) or "browser"

[llm]
default = "local-qwen"

[llm.providers.local-qwen]
type = "openai"
base_url = "http://localhost:11434/v1"
model = "qwen3:32b"
api_key = ""
supports_reasoning = true
native_tools = true

[sandbox]
backend = "auto"  # "auto" | "apple-containers" | "docker" | "podman" | "finch" | "none"

[persistence]
data_dir = "~/.stoiquent"
```

## Development

```bash
# Run tests
uv run pytest tests/unit/ -x -q
uv run pytest tests/integration/ -x -q

# Lint
uv run ruff check stoiquent/

# Coverage
uv run pytest --cov=stoiquent --cov-report=term-missing
```

## Architecture

See [docs/requirements.md](docs/requirements.md) and [docs/design.md](docs/design.md).
