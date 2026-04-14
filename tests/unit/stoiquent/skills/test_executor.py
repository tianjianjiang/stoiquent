from __future__ import annotations

from pathlib import Path

from stoiquent.skills.executor import build_command, resolve_script


def test_should_resolve_script_by_exact_name(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "greet.py").write_text("print('hi')")
    result = resolve_script(tmp_path, "greet.py")
    assert result is not None
    assert result.name == "greet.py"


def test_should_resolve_script_by_stem(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "greet.py").write_text("print('hi')")
    result = resolve_script(tmp_path, "greet")
    assert result is not None
    assert result.name == "greet.py"


def test_should_return_none_for_missing_script(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    assert resolve_script(tmp_path, "nonexistent") is None


def test_should_return_none_for_missing_scripts_dir(tmp_path: Path) -> None:
    assert resolve_script(tmp_path, "anything") is None


def test_should_build_python_command(tmp_path: Path) -> None:
    script = tmp_path / "test.py"
    script.write_text("#!/usr/bin/env python3\nprint('hello')")
    cmd = build_command(script)
    assert cmd == ["python3", str(script)]


def test_should_build_uv_run_for_pep723(tmp_path: Path) -> None:
    script = tmp_path / "test.py"
    script.write_text(
        "#!/usr/bin/env python3\n# /// script\n# dependencies = ['requests']\n# ///\n"
        "import requests\n"
    )
    cmd = build_command(script)
    assert cmd == ["uv", "run", str(script)]


def test_should_build_bash_command_from_shebang(tmp_path: Path) -> None:
    script = tmp_path / "test.sh"
    script.write_text("#!/bin/bash\necho hello")
    cmd = build_command(script)
    assert cmd == ["/bin/bash", str(script)]


def test_should_build_sh_command_for_unknown_extension(tmp_path: Path) -> None:
    script = tmp_path / "test.txt"
    script.write_text("echo hello")
    cmd = build_command(script)
    assert cmd == ["sh", str(script)]


def test_should_use_executable_directly(tmp_path: Path) -> None:
    script = tmp_path / "test"
    script.write_text("echo hello")
    script.chmod(0o755)
    cmd = build_command(script)
    assert cmd == [str(script)]


def test_should_detect_python_suffix_without_shebang(tmp_path: Path) -> None:
    script = tmp_path / "test.py"
    script.write_text("print('hello')")
    cmd = build_command(script)
    assert cmd == ["python3", str(script)]


def test_should_build_uv_run_for_pep723_without_shebang(tmp_path: Path) -> None:
    script = tmp_path / "test.py"
    script.write_text("# /// script\n# dependencies = ['requests']\n# ///\nimport requests\n")
    cmd = build_command(script)
    assert cmd == ["uv", "run", str(script)]


def test_should_reject_path_traversal(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "legit.py").write_text("print('hi')")
    result = resolve_script(tmp_path, "../../etc/passwd")
    assert result is None


def test_should_build_python_command_from_full_path_shebang(tmp_path: Path) -> None:
    script = tmp_path / "test.py"
    script.write_text("#!/usr/bin/python3\nprint('hello')")
    cmd = build_command(script)
    assert cmd == ["python3", str(script)]


def test_should_resolve_by_sorted_order(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "tool.py").write_text("print('py')")
    (scripts / "tool.sh").write_text("echo sh")
    result = resolve_script(tmp_path, "tool")
    assert result is not None
    assert result.name == "tool.py"


def test_should_handle_unreadable_shebang(tmp_path: Path) -> None:
    script = tmp_path / "test.py"
    script.write_text("print('hello')")
    script.chmod(0o000)
    try:
        cmd = build_command(script)
        assert "python3" in cmd[0] or "sh" in cmd[0]
    finally:
        script.chmod(0o644)
