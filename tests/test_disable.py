from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


CLAUDE_ABSENT = "other: npx other-server - Connected\n"
CLAUDE_PRESENT = "govdata: /Users/example/.local/bin/govdata-mcp - Failed\n"
CODEX_ABSENT = "Name Command Args Env Cwd Status Auth\nother npx - - - enabled Unsupported\n"
CODEX_PRESENT = (
    "Name Command Args Env Cwd Status Auth\n"
    "govdata /Users/example/.local/bin/govdata-mcp - - - enabled Unsupported\n"
)


class FakeTempDirectory:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def __enter__(self) -> str:
        return "/tmp/govdata-neutral"

    def __exit__(self, *_args: object) -> None:
        return None


def load_disable() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "disable.py"
    spec = importlib.util.spec_from_file_location("govdata_disable", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


disable = load_disable()


def configure_paths(monkeypatch: Any, *, govdata: str | None = "/opt/bin/govdata-mcp") -> None:
    paths = {
        "claude": "/opt/bin/claude",
        "codex": "/opt/bin/codex",
        "govdata-mcp": govdata,
    }
    monkeypatch.setattr(disable.shutil, "which", lambda name: paths.get(name))
    monkeypatch.setattr(disable.Path, "home", staticmethod(lambda: Path("/tmp/missing-home")))


def configure_run(
    monkeypatch: Any,
    *,
    claude_stdout: str,
    codex_stdout: str,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_run(
        args: list[str],
        *,
        dry_run: bool,
        check: bool = True,
        quiet: bool = False,
        cwd: Path | None = None,
    ) -> Any:
        calls.append(
            {
                "args": args,
                "dry_run": dry_run,
                "check": check,
                "quiet": quiet,
                "cwd": cwd,
            }
        )
        if args == ["claude", "mcp", "list"]:
            return disable.CommandResult(args=args, returncode=0, stdout=claude_stdout, stderr="")
        if args == ["codex", "mcp", "list"]:
            return disable.CommandResult(args=args, returncode=0, stdout=codex_stdout, stderr="")
        return disable.CommandResult(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(disable, "run", fake_run)
    return calls


def test_dry_run_enables_both_when_absent(monkeypatch: Any) -> None:
    configure_paths(monkeypatch)
    calls = configure_run(
        monkeypatch,
        claude_stdout=CLAUDE_ABSENT,
        codex_stdout=CODEX_ABSENT,
    )
    monkeypatch.setattr(disable.tempfile, "TemporaryDirectory", FakeTempDirectory)
    monkeypatch.setattr(disable.sys, "argv", ["disable.py", "--dry-run"])

    assert disable.main() == 0

    args = [call["args"] for call in calls]
    assert [
        "claude",
        "mcp",
        "add",
        "--transport",
        "stdio",
        "--scope",
        "user",
        "govdata",
        "--",
        "/opt/bin/govdata-mcp",
    ] in args
    assert ["codex", "mcp", "add", "govdata", "--", "/opt/bin/govdata-mcp"] in args
    assert ["claude", "mcp", "remove", "--scope", "user", "govdata"] not in args
    assert ["codex", "mcp", "remove", "govdata"] not in args


def test_dry_run_disables_both_when_codex_is_present(monkeypatch: Any) -> None:
    configure_paths(monkeypatch, govdata=None)
    calls = configure_run(
        monkeypatch,
        claude_stdout=CLAUDE_ABSENT,
        codex_stdout=CODEX_PRESENT,
    )
    monkeypatch.setattr(disable.tempfile, "TemporaryDirectory", FakeTempDirectory)
    monkeypatch.setattr(disable.sys, "argv", ["disable.py", "--dry-run"])

    assert disable.main() == 0

    args = [call["args"] for call in calls]
    assert ["claude", "mcp", "remove", "--scope", "user", "govdata"] in args
    assert ["codex", "mcp", "remove", "govdata"] in args
    assert not any(command[:3] == ["claude", "mcp", "add"] for command in args)
    assert not any(command[:3] == ["codex", "mcp", "add"] for command in args)


def test_mixed_state_disables_instead_of_inverting_each_client(monkeypatch: Any) -> None:
    configure_paths(monkeypatch, govdata=None)
    calls = configure_run(
        monkeypatch,
        claude_stdout=CLAUDE_PRESENT,
        codex_stdout=CODEX_ABSENT,
    )
    monkeypatch.setattr(disable.tempfile, "TemporaryDirectory", FakeTempDirectory)
    monkeypatch.setattr(disable.sys, "argv", ["disable.py", "--dry-run"])

    assert disable.main() == 0

    args = [call["args"] for call in calls]
    assert ["claude", "mcp", "remove", "--scope", "user", "govdata"] in args
    assert ["codex", "mcp", "remove", "govdata"] in args
    assert ["codex", "mcp", "add", "govdata", "--", "/opt/bin/govdata-mcp"] not in args


def test_missing_client_cli_exits_before_config_commands(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setattr(
        disable.shutil,
        "which",
        lambda name: None if name == "codex" else f"/opt/bin/{name}",
    )
    calls = configure_run(
        monkeypatch,
        claude_stdout=CLAUDE_ABSENT,
        codex_stdout=CODEX_ABSENT,
    )
    monkeypatch.setattr(disable.sys, "argv", ["disable.py", "--dry-run"])

    assert disable.main() == 1

    captured = capsys.readouterr()
    assert "required client CLI tools are missing" in captured.err
    assert "Codex CLI: `codex` was not found on PATH" in captured.err
    assert calls == []


def test_missing_mcp_binary_during_enable_exits_with_hint(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    configure_paths(monkeypatch, govdata=None)
    calls = configure_run(
        monkeypatch,
        claude_stdout=CLAUDE_ABSENT,
        codex_stdout=CODEX_ABSENT,
    )
    monkeypatch.setattr(disable.tempfile, "TemporaryDirectory", FakeTempDirectory)
    monkeypatch.setattr(disable.sys, "argv", ["disable.py", "--dry-run"])

    assert disable.main() == 1

    captured = capsys.readouterr()
    assert "govdata-mcp was not found on PATH" in captured.err
    assert "python3 install.py --all" in captured.err
    args = [call["args"] for call in calls]
    assert not any(command[1:3] == ["mcp", "add"] for command in args)
    assert not any(command[1:3] == ["mcp", "remove"] for command in args)


def test_detection_uses_neutral_temp_cwd(monkeypatch: Any) -> None:
    configure_paths(monkeypatch)
    calls = configure_run(
        monkeypatch,
        claude_stdout=CLAUDE_ABSENT,
        codex_stdout=CODEX_ABSENT,
    )
    monkeypatch.setattr(disable.tempfile, "TemporaryDirectory", FakeTempDirectory)
    monkeypatch.setattr(disable.sys, "argv", ["disable.py", "--dry-run"])

    assert disable.main() == 0

    list_calls = [
        call for call in calls if call["args"] in (["claude", "mcp", "list"], ["codex", "mcp", "list"])
    ]
    assert len(list_calls) == 2
    assert {call["cwd"] for call in list_calls} == {Path("/tmp/govdata-neutral")}
