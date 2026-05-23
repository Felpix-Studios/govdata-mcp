# Development

GovData MCP is a Python package at the repo root. The package name is
`govdata-mcp`, the server command is `govdata-mcp`, the auth command is
`govdata-auth`, and the registered MCP server name is `govdata`.

## Key Files

- `install.py` - root installer for `uv tool install` and Claude Code/Codex registration.
- `.mcp.json` - checked-in MCP config pointing at the installed `govdata-mcp` command.
- `.codex-plugin/plugin.json` - Codex plugin metadata.
- `src/govdata_mcp/server.py` - FastMCP server, tools, resources, prompts, and tool-profile filtering.
- `src/govdata_mcp/registry.py` - allowlisted agency and endpoint registry.
- `src/govdata_mcp/client.py` - HTTP execution, auth injection, redaction, saving, streaming, rate gates, and response envelopes.
- `src/govdata_mcp/router.py` - natural-language route planning and request defaults.
- `src/govdata_mcp/endpoint_docs.py` - endpoint parameter schema, examples, gotchas, and docs resources.
- `src/govdata_mcp/auth_store.py` - keyring/file-backed local auth CLI.

## Commands

```bash
uv sync --dev
UV_CACHE_DIR=/private/tmp/govdata-uv-cache uv run pytest
UV_CACHE_DIR=/private/tmp/govdata-uv-cache uv build
python3 install.py --dry-run --all --no-verify
python3 install.py --help
```

Use `UV_CACHE_DIR=/private/tmp/govdata-uv-cache` in restricted environments
where the default uv cache is unavailable.

## Architecture Notes

- Compact mode exposes only `govdata_query`, `govdata_find_dataset`, `govdata_get_dataset`, `govdata_guidance`, and `govdata_auth_status`.
- Full mode exposes only `govdata_*` tools.
- The generic upstream HTTP timeout is 600 seconds.
- IPUMS default polling waits up to 1800 seconds, with 60-second polls for the first 10 minutes and 300-second polls after that.
- FARA and NIH RePORTER use a 3-second rate gate.
- Saved API responses live under `data/govdata-downloads/responses`; IPUMS downloads live under `data/govdata-downloads/ipums`.

## Test Coverage

- `tests/test_guidance.py` checks guidance resources, auth resources, MCP config, and public docs constraints.
- `tests/test_router.py` checks compact/full profiles and route planning.
- `tests/test_endpoint_docs.py` checks endpoint docs, examples, stale endpoint metadata, and request-shape regressions.
- `tests/test_client.py` checks auth injection, redaction, redirects, binary responses, auto-save, streaming, and provider errors.
- `tests/test_ipums.py` checks IPUMS planning, extract creation/status/download behavior, and polling.
- `tests/test_installer.py` checks installer command shapes and dry-run behavior.

## Documentation Maintenance

- Keep public docs in `docs/`; do not add a top-level examples directory.
- Use current MCP resources for endpoint details instead of checking in giant generated matrices.
- Keep README concise and link to docs for details.
- Do not document removed provider-specific tool names.
- Do not include local absolute paths or secret values.
