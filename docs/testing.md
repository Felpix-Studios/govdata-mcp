# Testing

This document replaces static manual prompt files with a smaller validation
procedure grounded in live GovData MCP resources.

## Local Test Suite

Run:

```bash
UV_CACHE_DIR=/private/tmp/govdata-uv-cache uv run pytest
```

Useful focused checks:

```bash
uv run pytest tests/test_guidance.py
uv run pytest tests/test_router.py
uv run pytest tests/test_endpoint_docs.py
uv run pytest tests/test_client.py
```

## Installer Dry Run

```bash
python3 install.py --dry-run --all --no-verify
```

Expected behavior:

- prints `uv tool install --force --reinstall --refresh-package govdata-mcp`
- prints Claude Code and Codex registration commands
- does not modify client config
- works even when selected client CLIs are missing

## MCP Smoke Test

From an MCP client:

```text
govdata_auth_status(include_endpoints=false)
govdata_query(request="Search Data.gov for population datasets", execute=true, source_hint="datagov", limit=3)
```

Expected behavior:

- auth status returns configured key names and readiness without secret values
- Data.gov catalog search returns a source envelope with URL and status metadata
- no API key is required for the smoke test

## Registry And Docs Validation

From an MCP client:

```text
govdata_auth_status(include_endpoints=true)
govdata://agencies
govdata://guide
govdata://endpoint/fred/series_observations/examples
govdata://endpoint/census/data/parameters
```

Check that endpoint docs include parameter schema, auth notes, examples, docs
URLs, and source IDs. For provider-specific testing, start with endpoint docs and
make one bounded request through `govdata_query` or `govdata_get_dataset`.

## Manual Matrix Strategy

For broad manual validation, build the matrix dynamically:

1. Call `govdata_auth_status(include_endpoints=true)`.
2. Read `govdata://agencies`.
3. For each active agency, read `govdata://agency/{agency_id}/docs`.
4. For selected endpoints, read `govdata://endpoint/{agency_id}/{endpoint_id}/examples`.
5. Execute bounded requests through compact tools only.
6. Save large or file-like outputs under a dedicated `data/` subdirectory.
7. Record source URL, docs URL, HTTP status, retrieved time, saved path, byte count, and SHA-256 hash.

Use these status labels for reports:

```text
PASS
PASS_WITH_WARNING
SKIP_AUTH_MISSING
NEEDS_INPUT
AMBIGUOUS
UPSTREAM_ERROR
MCP_ERROR
NOT_RUN
```

Reserve `MCP_ERROR` for tooling, routing, parsing, saving, stream handling, or
MCP serialization failures. If GovData returns a provider response envelope with
HTTP 4xx or 5xx, classify it as `UPSTREAM_ERROR`.

## Regression Guards

Do not reintroduce these stale request shapes:

- hard-coded placeholder IPUMS extract numbers instead of values returned by `create_extract`
- FTC HSR queries that send unsupported `limit`
- NREL nearest-station queries using a free-form `location` parameter
- CrimeSolutions CSV feeds with Socrata-style `$limit`
- Data USA legacy `Geography` filters against the current Tesseract endpoint

Use current docs resources and bounded parameters instead.
