#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


SERVER_NAME = "govdata"
MCP_COMMAND = "govdata-mcp"
CLIENT_COMMANDS = {
    "claude": "claude",
    "codex": "codex",
}
CLIENT_LABELS = {
    "claude": "Claude Code CLI",
    "codex": "Codex CLI",
}


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ToggleState:
    claude_registered: bool
    codex_registered: bool

    @property
    def any_registered(self) -> bool:
        return self.claude_registered or self.codex_registered


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    missing_clients = missing_client_commands()
    if missing_clients:
        print("Cannot toggle GovData MCP because required client CLI tools are missing.", file=sys.stderr)
        for client in missing_clients:
            print(f"- {CLIENT_LABELS[client]}: `{CLIENT_COMMANDS[client]}` was not found on PATH.", file=sys.stderr)
        return 1

    print("GovData MCP config toggle")
    try:
        with tempfile.TemporaryDirectory(prefix="govdata-mcp-toggle-") as temp_dir:
            state = detect_toggle_state(Path(temp_dir))
    except RuntimeError as exc:
        print(f"Unable to inspect MCP client config: {exc}", file=sys.stderr)
        return 1

    print_toggle_state(state)

    if state.any_registered:
        print("\nDisabling GovData MCP for Claude Code and Codex...")
        try:
            disable_clients(dry_run=args.dry_run)
        except RuntimeError as exc:
            print(f"Unable to disable GovData MCP: {exc}", file=sys.stderr)
            return 1
        finish("disabled", dry_run=args.dry_run)
        return 0

    mcp_bin = resolve_mcp_binary()
    if not mcp_bin:
        print(
            "govdata-mcp was not found on PATH. Run `python3 install.py --all` "
            "before enabling client registrations.",
            file=sys.stderr,
        )
        return 1

    print(f"GovData MCP command: {mcp_bin}")
    print("\nEnabling GovData MCP for Claude Code and Codex...")
    try:
        enable_clients(mcp_bin, dry_run=args.dry_run)
    except RuntimeError as exc:
        print(f"Unable to enable GovData MCP: {exc}", file=sys.stderr)
        return 1
    finish("enabled", dry_run=args.dry_run)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Toggle the global/user GovData MCP registration for Claude Code "
            "and the Codex CLI."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the commands that would run without changing client config",
    )
    return parser


def missing_client_commands() -> list[str]:
    return [
        client
        for client, command in CLIENT_COMMANDS.items()
        if shutil.which(command) is None
    ]


def detect_toggle_state(cwd: Path) -> ToggleState:
    return ToggleState(
        claude_registered=detect_claude_registration(cwd),
        codex_registered=detect_codex_registration(cwd),
    )


def detect_claude_registration(cwd: Path) -> bool:
    result = run(
        ["claude", "mcp", "list"],
        dry_run=False,
        check=True,
        quiet=True,
        cwd=cwd,
    )
    return output_mentions_server(result.stdout, SERVER_NAME)


def detect_codex_registration(cwd: Path) -> bool:
    result = run(
        ["codex", "mcp", "list"],
        dry_run=False,
        check=True,
        quiet=True,
        cwd=cwd,
    )
    return output_mentions_server(result.stdout, SERVER_NAME)


def output_mentions_server(output: str, server_name: str) -> bool:
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(f"{server_name}:"):
            return True
        fields = stripped.split()
        if fields and fields[0] == server_name:
            return True
    return False


def print_toggle_state(state: ToggleState) -> None:
    print("\nCurrent client registrations:")
    print(f"- Claude Code user registration: {format_registration(state.claude_registered)}")
    print(f"- Codex global registration: {format_registration(state.codex_registered)}")


def format_registration(registered: bool) -> str:
    return "present" if registered else "not found"


def resolve_mcp_binary() -> str | None:
    expected = Path.home() / ".local" / "bin" / MCP_COMMAND
    if expected.exists():
        return str(expected)
    return shutil.which(MCP_COMMAND)


def disable_clients(*, dry_run: bool) -> None:
    run(["claude", "mcp", "remove", "--scope", "user", SERVER_NAME], dry_run=dry_run, check=False)
    run(["codex", "mcp", "remove", SERVER_NAME], dry_run=dry_run, check=False)


def enable_clients(mcp_bin: str, *, dry_run: bool) -> None:
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
    run(["codex", "mcp", "add", SERVER_NAME, "--", mcp_bin], dry_run=dry_run)


def finish(action: str, *, dry_run: bool) -> None:
    if dry_run:
        print("\nDry run complete. No changes were made.")
    else:
        print(f"\nGovData MCP {action}. Restart any open Claude Code or Codex sessions.")


def run(
    args: list[str],
    *,
    dry_run: bool,
    check: bool = True,
    quiet: bool = False,
    cwd: Path | None = None,
) -> CommandResult:
    if not quiet:
        print(f"$ {shlex.join(args)}")
    if dry_run:
        return CommandResult(args=args, returncode=0, stdout="", stderr="")

    completed = subprocess.run(
        args,
        check=False,
        cwd=cwd,
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
