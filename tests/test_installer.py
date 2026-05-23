from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def load_installer() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "install.py"
    spec = importlib.util.spec_from_file_location("govdata_install", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


installer = load_installer()


def test_install_mcp_package_uses_repo_root(capsys: Any) -> None:
    installer.install_mcp_package(Path("/repo/govdata"), dry_run=True)

    output = capsys.readouterr().out
    assert "$ uv tool install --force --reinstall --refresh-package govdata-mcp /repo/govdata" in output
    assert "plugins/govdata" not in output


def test_client_preflight_reports_cli_paths_and_config_delegation(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    paths = {
        "claude": "/opt/homebrew/bin/claude",
        "codex": "/Users/example/.local/bin/codex",
    }
    monkeypatch.setattr(installer.shutil, "which", lambda name: paths.get(name))

    checks = installer.inspect_client_preflight(["claude", "codex"])
    installer.print_client_preflight(checks)

    output = capsys.readouterr().out
    assert "- Claude Code CLI: found at /opt/homebrew/bin/claude" in output
    assert "- Codex CLI: found at /Users/example/.local/bin/codex" in output
    assert "Registration will use: claude mcp add --transport stdio --scope user govdata -- <govdata-mcp>" in output
    assert "Registration will use: codex mcp add govdata -- <govdata-mcp>" in output
    assert "does not directly create or edit ~/.claude, ~/.claude.json, or ~/.codex" in output


def test_dry_run_registers_claude_and_codex_without_clis(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setattr(installer.shutil, "which", lambda _name: None)
    mcp_bin = "/Users/example/.local/bin/govdata-mcp"

    installer.configure_claude(mcp_bin, dry_run=True, verify=True)
    installer.configure_codex(mcp_bin, dry_run=True, verify=True)

    output = capsys.readouterr().out
    assert "$ claude mcp remove --scope user govdata" in output
    assert f"$ claude mcp add --transport stdio --scope user govdata -- {mcp_bin}" in output
    assert "$ claude mcp get govdata" in output
    assert "$ codex mcp remove govdata" in output
    assert f"$ codex mcp add govdata -- {mcp_bin}" in output
    assert "$ codex mcp get govdata" in output


def test_dry_run_uninstall_prints_client_and_package_commands(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setattr(installer.shutil, "which", lambda _name: None)

    failures = installer.uninstall_selected_clients(["claude", "codex"], dry_run=True)
    installer.uninstall_mcp_package(dry_run=True)

    output = capsys.readouterr().out
    assert failures == []
    assert "$ claude mcp remove --scope user govdata" in output
    assert "$ codex mcp remove govdata" in output
    assert "$ uv tool uninstall govdata-mcp" in output


def test_real_registration_requires_selected_cli(monkeypatch: Any) -> None:
    monkeypatch.setattr(installer.shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError, match="Claude Code CLI"):
        installer.configure_claude("/missing/govdata-mcp", dry_run=False, verify=True)

    with pytest.raises(RuntimeError, match="Codex CLI"):
        installer.configure_codex("/missing/govdata-mcp", dry_run=False, verify=True)


def test_main_dry_run_all_works_without_external_clis(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setattr(installer.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        installer.sys,
        "argv",
        ["install.py", "--dry-run", "--all", "--no-verify"],
    )

    assert installer.main() == 0

    output = capsys.readouterr().out
    assert "GovData MCP installer" in output
    assert "$ uv tool install --force --reinstall --refresh-package govdata-mcp" in output
    assert "plugins/govdata" not in output
    assert "$ claude mcp add --transport stdio --scope user govdata --" in output
    assert "$ codex mcp add govdata --" in output


def test_main_non_dry_run_fails_before_package_install_when_cli_missing(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setattr(installer.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        installer.sys,
        "argv",
        ["install.py", "--all", "--force-reinstall", "--no-verify"],
    )

    assert installer.main() == 1

    captured = capsys.readouterr()
    assert "Install cannot continue because selected client CLI tools are missing." in captured.err
    assert "Claude Code CLI: `claude` was not found on PATH." in captured.err
    assert "Codex CLI: `codex` was not found on PATH." in captured.err
    assert "$ uv tool install" not in captured.out
