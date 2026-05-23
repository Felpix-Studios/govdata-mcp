#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


SERVER_NAME = "govdata"
CLIENT_CHOICES = ("claude", "codex")
CLIENT_COMMANDS = {
    "claude": "claude",
    "codex": "codex",
}
CLIENT_LABELS = {
    "claude": "Claude Code CLI",
    "codex": "Codex CLI",
}
CLIENT_REGISTRATION_COMMANDS = {
    "claude": "claude mcp add --transport stdio --scope user govdata -- <govdata-mcp>",
    "codex": "codex mcp add govdata -- <govdata-mcp>",
}


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class InstallState:
    package_installed: bool
    mcp_bin: str | None
    claude_registered: bool
    codex_registered: bool

    @property
    def any_installed(self) -> bool:
        return self.package_installed or self.claude_registered or self.codex_registered


@dataclass(frozen=True)
class ClientPreflight:
    client: str
    command: str
    label: str
    path: str | None
    registration_command: str

    @property
    def available(self) -> bool:
        return self.path is not None


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    package_dir = root
    missing_package_files = [
        path
        for path in (
            package_dir / "pyproject.toml",
            package_dir / "src" / "govdata_mcp" / "server.py",
        )
        if not path.exists()
    ]
    if missing_package_files:
        missing = ", ".join(str(path) for path in missing_package_files)
        print(f"Missing package file(s): {missing}", file=sys.stderr)
        return 1

    selected_clients = select_clients(args)
    if not selected_clients:
        print("No clients selected. Nothing to install.")
        return 0

    print("GovData MCP installer")
    print(f"Repository: {root}")
    print(f"Clients: {', '.join(selected_clients)}")

    client_preflight = inspect_client_preflight(selected_clients)
    print_client_preflight(client_preflight)

    state = detect_install_state(selected_clients)
    print_install_state(state)

    action = select_install_action(args, state)
    if action == "uninstall":
        failures = uninstall_selected_clients(selected_clients, dry_run=args.dry_run)
        if not args.keep_package:
            if not args.dry_run and not require_command("uv"):
                return 1
            uninstall_mcp_package(dry_run=args.dry_run)
        if failures:
            print("\nUninstall finished with errors:", file=sys.stderr)
            for failure in failures:
                print(f"- {failure}", file=sys.stderr)
            return 1
        print("\nUninstall complete." if not args.dry_run else "\nDry run complete. No changes were made.")
        return 0

    if action == "none":
        print("No changes made.")
        return 0

    missing_clients = missing_preflight_clients(client_preflight)
    if missing_clients and not args.dry_run:
        print("\nInstall cannot continue because selected client CLI tools are missing.", file=sys.stderr)
        for check in missing_clients:
            print(f"- {check.label}: `{check.command}` was not found on PATH.", file=sys.stderr)
        print("Install the missing CLI tools or rerun with only the clients you want to configure.", file=sys.stderr)
        return 1

    if not args.skip_package_install:
        if not args.dry_run and not require_command("uv"):
            return 1
        install_mcp_package(package_dir, dry_run=args.dry_run)

    mcp_bin = resolve_mcp_binary(dry_run=args.dry_run)
    print(f"GovData MCP command: {mcp_bin}")

    failures: list[str] = []
    if "claude" in selected_clients:
        try:
            configure_claude(mcp_bin, dry_run=args.dry_run, verify=not args.no_verify)
        except RuntimeError as exc:
            failures.append(str(exc))

    if "codex" in selected_clients:
        try:
            configure_codex(mcp_bin, dry_run=args.dry_run, verify=not args.no_verify)
        except RuntimeError as exc:
            failures.append(str(exc))

    if failures:
        print("\nInstall finished with errors:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\nDry run complete. No changes were made.")
    else:
        print("\nInstall complete. Restart any open Claude Code or Codex sessions.")
        print("Use `govdata-auth setup` separately to configure API keys.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Install GovData MCP globally and register it with Claude Code, "
            "Codex, or both."
        )
    )
    parser.add_argument(
        "--claude",
        action="store_true",
        help="register GovData as a user-scoped Claude Code MCP server",
    )
    parser.add_argument(
        "--codex",
        action="store_true",
        help="register GovData as a global Codex MCP server",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="register both Claude Code and Codex without showing the checklist",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="do not show the checklist; defaults to both clients if none are selected",
    )
    parser.add_argument(
        "--skip-package-install",
        action="store_true",
        help="skip uv tool install and only register the existing govdata-mcp command",
    )
    parser.add_argument(
        "--force-reinstall",
        action="store_true",
        help="reinstall the package and re-register selected clients when an install exists",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="remove selected client registrations and uninstall the govdata-mcp uv tool",
    )
    parser.add_argument(
        "--keep-package",
        action="store_true",
        help="with --uninstall, remove client registrations but keep the govdata-mcp uv tool",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip `claude mcp get` and `codex mcp get` verification after registration",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the commands that would run without changing global config",
    )
    return parser


def select_clients(args: argparse.Namespace) -> list[str]:
    if args.all:
        return list(CLIENT_CHOICES)

    selected = []
    if args.claude:
        selected.append("claude")
    if args.codex:
        selected.append("codex")
    if selected:
        return selected

    if args.non_interactive or not sys.stdin.isatty():
        return list(CLIENT_CHOICES)

    return interactive_client_checklist()


def select_install_action(args: argparse.Namespace, state: InstallState) -> str:
    if args.uninstall:
        return "uninstall"
    if args.dry_run:
        return "install"
    if args.force_reinstall:
        return "install"
    if not state.any_installed:
        return "install"

    if args.non_interactive or not sys.stdin.isatty():
        print("Existing install detected; use --force-reinstall or --uninstall to change it.")
        return "none"

    return interactive_install_action()


def interactive_install_action() -> str:
    while True:
        print("\nExisting GovData MCP install detected. Choose an action:")
        print("  1. Force reinstall selected clients")
        print("  2. Uninstall selected clients")
        print("  3. Leave unchanged")
        choice = input("> ").strip().lower()
        if choice in {"1", "r", "reinstall", "force", "force reinstall"}:
            return "install"
        if choice in {"2", "u", "uninstall", "remove"}:
            return "uninstall"
        if choice in {"", "3", "n", "no", "none", "skip", "q", "quit"}:
            return "none"
        print("Choose 1, 2, or 3.")


def interactive_client_checklist() -> list[str]:
    available_clients = {
        client
        for client in CLIENT_CHOICES
        if shutil.which(CLIENT_COMMANDS[client])
    }
    selected = set(available_clients or CLIENT_CHOICES)
    labels = {
        "claude": "Claude Code user-scope MCP registration",
        "codex": "Codex global MCP registration",
    }

    while True:
        print("\nSelect clients to configure:")
        for index, client in enumerate(CLIENT_CHOICES, start=1):
            mark = "x" if client in selected else " "
            command = CLIENT_COMMANDS[client]
            path = shutil.which(command)
            status = f"found at {path}" if path else "not found on PATH"
            print(f"  [{mark}] {index}. {labels[client]} ({status})")
        print("Press 1 or 2 to toggle. Press Enter to continue. Press q to quit.")
        choice = input("> ").strip().lower()
        if choice == "":
            return [client for client in CLIENT_CHOICES if client in selected]
        if choice in {"q", "quit", "exit"}:
            return []
        if choice in {"1", "2"}:
            client = CLIENT_CHOICES[int(choice) - 1]
            if client in selected:
                selected.remove(client)
            else:
                selected.add(client)
            continue
        print("Choose 1, 2, Enter, or q.")


def inspect_client_preflight(selected_clients: list[str]) -> list[ClientPreflight]:
    checks: list[ClientPreflight] = []
    for client in selected_clients:
        command = CLIENT_COMMANDS[client]
        checks.append(
            ClientPreflight(
                client=client,
                command=command,
                label=CLIENT_LABELS[client],
                path=shutil.which(command),
                registration_command=CLIENT_REGISTRATION_COMMANDS[client],
            )
        )
    return checks


def print_client_preflight(checks: list[ClientPreflight]) -> None:
    print("\nClient preflight:")
    for check in checks:
        if check.available:
            print(f"- {check.label}: found at {check.path}")
            print(f"  Registration will use: {check.registration_command}")
            print(f"  Config location is managed by the {check.label}.")
        else:
            print(f"- {check.label}: not found on PATH")
            print(f"  GovData cannot register this client until `{check.command}` is installed.")
    print(
        "Config note: The installer does not directly create or edit ~/.claude, "
        "~/.claude.json, or ~/.codex."
    )


def missing_preflight_clients(checks: list[ClientPreflight]) -> list[ClientPreflight]:
    return [check for check in checks if not check.available]


def detect_install_state(selected_clients: list[str]) -> InstallState:
    mcp_bin = shutil.which("govdata-mcp")
    package_installed = bool(mcp_bin)
    claude_registered = False
    codex_registered = False

    if "claude" in selected_clients and shutil.which("claude"):
        result = run(
            ["claude", "mcp", "get", SERVER_NAME],
            dry_run=False,
            check=False,
            quiet=True,
        )
        claude_registered = result.returncode == 0

    if "codex" in selected_clients and shutil.which("codex"):
        result = run(
            ["codex", "mcp", "get", SERVER_NAME],
            dry_run=False,
            check=False,
            quiet=True,
        )
        codex_registered = result.returncode == 0

    return InstallState(
        package_installed=package_installed,
        mcp_bin=mcp_bin,
        claude_registered=claude_registered,
        codex_registered=codex_registered,
    )


def print_install_state(state: InstallState) -> None:
    print("\nCurrent install state:")
    print(f"- govdata-mcp command: {state.mcp_bin or 'not found'}")
    print(f"- Claude Code registration: {'present' if state.claude_registered else 'not found'}")
    print(f"- Codex registration: {'present' if state.codex_registered else 'not found'}")


def install_mcp_package(package_dir: Path, *, dry_run: bool) -> None:
    run(
        [
            "uv",
            "tool",
            "install",
            "--force",
            "--reinstall",
            "--refresh-package",
            "govdata-mcp",
            str(package_dir),
        ],
        dry_run=dry_run,
    )


def uninstall_mcp_package(*, dry_run: bool) -> None:
    run(["uv", "tool", "uninstall", "govdata-mcp"], dry_run=dry_run, check=False)


def resolve_mcp_binary(*, dry_run: bool) -> str:
    expected = Path.home() / ".local" / "bin" / "govdata-mcp"
    if expected.exists():
        return str(expected)

    existing = shutil.which("govdata-mcp")
    if existing:
        return existing

    if dry_run:
        return str(expected)

    raise RuntimeError(
        "govdata-mcp was not found on PATH after install. "
        "Try opening a new shell or running `uv tool update-shell`."
    )


def uninstall_selected_clients(selected_clients: list[str], *, dry_run: bool) -> list[str]:
    failures: list[str] = []

    if "claude" in selected_clients:
        if dry_run or require_command("claude"):
            try:
                print("\nRemoving Claude Code registration...")
                run(["claude", "mcp", "remove", "--scope", "user", SERVER_NAME], dry_run=dry_run, check=False)
            except RuntimeError as exc:
                failures.append(str(exc))
        else:
            failures.append("Claude Code CLI `claude` was not found on PATH.")

    if "codex" in selected_clients:
        if dry_run or require_command("codex"):
            try:
                print("\nRemoving Codex registration...")
                run(["codex", "mcp", "remove", SERVER_NAME], dry_run=dry_run, check=False)
            except RuntimeError as exc:
                failures.append(str(exc))
        else:
            failures.append("Codex CLI `codex` was not found on PATH.")

    return failures


def configure_claude(mcp_bin: str, *, dry_run: bool, verify: bool) -> None:
    if not dry_run and not require_command("claude"):
        raise RuntimeError("Claude Code CLI `claude` was not found on PATH.")

    print("\nConfiguring Claude Code...")
    run(["claude", "mcp", "remove", "--scope", "user", SERVER_NAME], dry_run=dry_run, check=False)
    run(
        [
            "claude",
            "mcp",
            "add",
            "--transport",
            "stdio",
            "--scope",
            "user",
            SERVER_NAME,
            "--",
            mcp_bin,
        ],
        dry_run=dry_run,
    )
    if verify:
        run(["claude", "mcp", "get", SERVER_NAME], dry_run=dry_run)


def configure_codex(mcp_bin: str, *, dry_run: bool, verify: bool) -> None:
    if not dry_run and not require_command("codex"):
        raise RuntimeError("Codex CLI `codex` was not found on PATH.")

    print("\nConfiguring Codex...")
    run(["codex", "mcp", "remove", SERVER_NAME], dry_run=dry_run, check=False)
    run(["codex", "mcp", "add", SERVER_NAME, "--", mcp_bin], dry_run=dry_run)
    if verify:
        run(["codex", "mcp", "get", SERVER_NAME], dry_run=dry_run)


def require_command(name: str) -> bool:
    if shutil.which(name):
        return True
    print(f"Required command not found on PATH: {name}", file=sys.stderr)
    return False


def run(
    args: list[str],
    *,
    dry_run: bool,
    check: bool = True,
    quiet: bool = False,
) -> CommandResult:
    if not quiet:
        print(f"$ {shlex.join(args)}")
    if dry_run:
        return CommandResult(args=args, returncode=0, stdout="", stderr="")

    completed = subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.stdout and not quiet:
        print(completed.stdout, end="")
    if completed.stderr and not quiet:
        print(completed.stderr, end="", file=sys.stderr)

    result = CommandResult(
        args=args,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {shlex.join(args)}"
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
