# Troubleshooting

## Package Import Fails

Check the local package:

```bash
uv run python -c "import govdata_mcp.server; print('ok')"
```

If this fails, run:

```bash
uv sync --dev
```

## Client Cannot See The Server

Check commands and registration:

```bash
command -v govdata-mcp
command -v govdata-auth
claude mcp get govdata
codex mcp get govdata
```

Refresh registration:

```bash
python3 install.py --all --force-reinstall
```

The installer should register the stable shim path, usually
`~/.local/bin/govdata-mcp`, instead of a transient internal `uv` tool path.

## Missing API Key

Inspect safe readiness:

```bash
govdata-auth list
govdata-auth path
```

From an MCP client:

```text
govdata_auth_status(include_endpoints=true)
```

Add missing keys with `govdata-auth setup` or `govdata-auth set NAME`, then
restart the MCP client session.

## Provider 403 Or 429

- `403` usually means the key is missing, invalid, not entitled for that provider, or sent in the wrong auth location.
- `429` means the provider is throttling. Retry later with a smaller request.
- FARA and NIH RePORTER calls are automatically spaced by 3 seconds.

## Large Or Binary Responses

GovData saves large, binary, streamed, or attachment-like responses instead of
returning them inline. Check the response envelope for:

- saved path
- content type
- byte count
- SHA-256 hash
- source URL

Ordinary saved responses default to `data/govdata-downloads/responses`. IPUMS
downloads default to `data/govdata-downloads/ipums`.

## Stale Or Changed Upstream Routes

Some government APIs move, redirect, or remove endpoints without notice. GovData
tries to keep stale routes marked in registry/docs and return structured errors
instead of failing silently.

Useful next steps:

```text
govdata://agency/{agency_id}/docs
govdata://endpoint/{agency_id}/{endpoint_id}/docs
govdata_find_dataset(action="examples", agency_id="epa", endpoint_id="facility_report")
```

If endpoint docs show alternatives, use the alternative route. If a provider
returns a response envelope with HTTP 4xx or 5xx, preserve the source URL,
status, and error body in your report.

## Ambiguous Or Needs Input

If `govdata_query` returns `ambiguous`, provide `source_hint` or `route_id`.
If it returns `needs_input`, provide the missing `path_params`, `query`, or
`body` fields named in the response.

Examples:

```text
govdata_query(request="Fetch CPI data", source_hint="bls")
govdata_query(route_id="fec.elections", query={"office":"senate","state":"CA"})
```
