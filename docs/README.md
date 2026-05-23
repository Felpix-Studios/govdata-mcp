# GovData MCP Docs

This directory is the public documentation set for GovData MCP.

## Start Here

- [Install](install.md) - clone install, update, dry-run, and uninstall.
- [MCP Clients](mcp-clients.md) - Claude Code, Codex, `.mcp.json`, and tool profiles.
- [Auth](auth.md) - API keys, persisted auth, key mapping, and safe status checks.
- [Tools](tools.md) - compact tools, full-mode tools, resources, and prompts.
- [Endpoints And Data Sources](endpoints.md) - source catalog and endpoint notes.
- [Workflows](workflows.md) - practical query, discovery, save, and extract workflows.
- [Testing](testing.md) - smoke tests and manual validation procedure.
- [Troubleshooting](troubleshooting.md) - common install, auth, provider, and MCP issues.
- [Development](development.md) - architecture, test commands, packaging, and maintenance.

## Documentation Rules

- Keep docs grounded in current code, tests, and MCP resources.
- Prefer purpose-first source descriptions over long endpoint tables.
- Keep secrets out of docs and examples.
- Use `govdata_*` tools in examples; do not document removed provider-specific tool names.
- Use `govdata://...` resources for live endpoint details instead of copying large generated matrices into the repo.
