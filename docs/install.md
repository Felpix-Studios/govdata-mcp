# Install

GovData MCP is installed from a local clone. The installer uses `uv tool install`
to install the package globally, then registers the installed `govdata-mcp`
command with Claude Code, Codex, or both.

## Prerequisites

- Python 3.11 or newer.
- `uv` on `PATH`.
- Claude Code, Codex, or both if you want automatic client registration.

## Fresh Install

```bash
git clone https://github.com/Felpix-Studios/govdata-mcp.git
cd govdata-mcp
python3 install.py --all
govdata-auth setup
```

Use one client flag when you do not want both registrations:

```bash
python3 install.py --claude
python3 install.py --codex
```

## Verify

```bash
command -v govdata-mcp
command -v govdata-auth
claude mcp get govdata
codex mcp get govdata
```

Run the server directly only as a smoke check. It is a stdio server and waits for
an MCP client:

```bash
govdata-mcp
```

Press `Ctrl+C` to stop it.

## Update

After pulling changes from the repo, reinstall and refresh client registration:

```bash
git pull
python3 install.py --all --force-reinstall
```

## Dry Run

Print the package and registration commands without changing global config:

```bash
python3 install.py --dry-run --all --no-verify
```

Dry-run mode does not require the Claude Code or Codex CLI binaries to be
installed.

## Uninstall

Remove client registrations and uninstall the `uv` tool package:

```bash
python3 install.py --all --uninstall
```

Remove client registrations but keep the package:

```bash
python3 install.py --all --uninstall --keep-package
```

The installer delegates config changes to the client CLIs. It does not directly
edit `~/.claude`, `~/.claude.json`, or `~/.codex`.
