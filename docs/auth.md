# Auth

GovData MCP reads API keys from environment variables first, then from the local
persisted auth store. Environment variables always override saved values.

## Configure Keys

Run the interactive setup:

```bash
govdata-auth setup
```

Inspect configured key names without exposing values:

```bash
govdata-auth list
govdata-auth path
```

Set or delete one value:

```bash
govdata-auth set FRED_API_KEY
govdata-auth delete FRED_API_KEY
```

The default store is the OS keyring when available. If keyring is unavailable,
GovData falls back to `~/.config/govdata-mcp/secrets.env`. Use `--store file`
or `--store keyring` to choose explicitly.

## MCP Status

From an MCP client, use either:

```text
govdata_auth_status
govdata://auth/status
```

Pass `include_endpoints=true` when you need endpoint-level readiness. The status
response reports configured key names, auth kinds, missing key names, and endpoint
auth state. It never returns secret values.

## Supported Names

```text
API_DATA_GOV_KEY
CENSUS_API_KEY
BLS_API_KEY
EIA_API_KEY
FDA_API_KEY
FRED_API_KEY
IPUMS_API_KEY
NREL_API_KEY
NOAA_TOKEN
GOVDATA_ALLOW_DEMO_KEY
```

`NOAA_TOKEN` is recognized by the auth registry, but current active endpoints do
not use it. `GOVDATA_ALLOW_DEMO_KEY=1` permits `DEMO_KEY` fallback only for
endpoints whose metadata explicitly declares a demo key.

## Source Mapping

- `API_DATA_GOV_KEY` - shared key for many participating federal APIs, including FoodData Central, Commerce, College Scorecard, DOJ/BJS/CrimeSolutions, EIA fallback, openFDA fallback, FEC, FTC, govinfo, Congress.gov, and NREL fallback.
- `CENSUS_API_KEY` - Census Data API.
- `BLS_API_KEY` - optional BLS registration key for higher limits.
- `EIA_API_KEY` - EIA-specific key; falls back to `API_DATA_GOV_KEY`.
- `FDA_API_KEY` - openFDA-specific key; falls back to `API_DATA_GOV_KEY`.
- `FRED_API_KEY` - Federal Reserve Economic Data.
- `IPUMS_API_KEY` - IPUMS metadata, extracts, polling, and downloads.
- `NREL_API_KEY` - National Laboratory of the Rockies Developer Network; falls back to `API_DATA_GOV_KEY`.

## Safety Rules

- Do not put API keys in `.mcp.json`, prompts, docs, examples, logs, or checked-in files.
- Treat auth status output as readiness metadata, not as a source of secrets.
- Restart Claude Code, Codex, or any long-running MCP client after adding keys so the server reloads persisted auth.
- If a provider returns `403`, confirm both the key and the auth location expected by that provider.
