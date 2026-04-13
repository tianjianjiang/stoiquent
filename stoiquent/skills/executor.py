from __future__ import annotations

import logging
import stat
from pathlib import Path

logger = logging.getLogger(__name__)


def resolve_script(skill_path: Path, script_name: str) -> Path | None:
    """Find a script in the skill's scripts/ directory."""
    scripts_dir = skill_path / "scripts"
    if not scripts_dir.is_dir():
        return None

    candidate = scripts_dir / script_name
    if candidate.is_file() and _is_within(candidate, scripts_dir):
        return candidate

    for entry in sorted(scripts_dir.iterdir()):
        if entry.stem == script_name and entry.is_file():
            return entry

    return None


def build_command(script_path: Path) -> list[str]:
    """Build a command list from a script, detecting the runner via shebang."""
    shebang = _read_shebang(script_path)

    if shebang:
        parts = shebang.split()
        interpreter = Path(parts[-1]).name
        if interpreter in ("python3", "python"):
            if _has_pep723_metadata(script_path):
                return ["uv", "run", str(script_path)]
            return ["python3", str(script_path)]
        return [*parts, str(script_path)]

    if script_path.suffix == ".py":
        if _has_pep723_metadata(script_path):
            return ["uv", "run", str(script_path)]
        return ["python3", str(script_path)]

    if _is_executable(script_path):
        return [str(script_path)]

    return ["sh", str(script_path)]


def _read_shebang(path: Path) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line.startswith("#!"):
            return first_line[2:].strip()
    except OSError:
        pass
    return None


def _has_pep723_metadata(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
        return "# /// script" in text
    except OSError:
        return False


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _is_executable(path: Path) -> bool:
    try:
        return bool(path.stat().st_mode & stat.S_IXUSR)
    except OSError:
        return False
