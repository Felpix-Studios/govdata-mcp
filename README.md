# GovData MCP

> U.S. government data all in one place for Claude Code, Codex, and other MCP clients.

GovData MCP is a local Model Context Protocol server for discovering, querying,
and downloading public U.S. government data. It wraps government APIs with a
consistent MCP interface, source metadata, endpoint examples, local auth
handling, and safe downloads.

## Quickstart

Prerequisites:

- Python 3.11 or newer
- `uv`
- Claude Code, Codex, or another MCP client

Install from a clone and register the server with Claude Code and Codex:

```bash
git clone https://github.com/Felpix-Studios/govdata-mcp.git
cd govdata-mcp
python3 install.py --all
govdata-auth setup
```

The installer installs the `govdata-mcp` and `govdata-auth` commands, then
registers `govdata-mcp` with the selected MCP client. To configure only one
client, use `--claude` or `--codex`:

```bash
python3 install.py --claude
python3 install.py --codex
```

After pulling updates, reinstall and refresh client registration:

```bash
python3 install.py --all --force-reinstall
```

Check the installed commands:

```bash
command -v govdata-mcp
command -v govdata-auth
```

Run the server directly only as a smoke check. It uses stdio and will wait for
an MCP client:

```bash
govdata-mcp
```

Press `Ctrl+C` to stop it.

## Documentation

Detailed docs live in [`docs/`](docs/README.md):

- [Install](docs/install.md)
- [MCP clients](docs/mcp-clients.md)
- [Auth](docs/auth.md)
- [Tools](docs/tools.md)
- [Endpoints and data sources](docs/endpoints.md)
- [Workflows](docs/workflows.md)
- [Testing](docs/testing.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Development](docs/development.md)

## First Prompts

Use these from Claude Code, Codex, or another connected MCP client:

```text
Use the govdata MCP to check auth status.
Use the govdata MCP to search Data.gov for county-level opioid datasets.
Use the govdata MCP to fetch BLS CPI series CUUR0000SA0 for 2020 through 2025.
Use the govdata MCP to fetch FRED GDP observations and cite the request.
Use the govdata MCP to download 2023 ACS5 variables metadata.
Use the govdata MCP to plan an IPUMS extract for ACS or CPS microdata.
```

## Claude Code

Install and register GovData MCP for Claude Code:

```bash
python3 install.py --claude
```

Verify the registration:

```bash
claude mcp list
claude mcp get govdata
```

Start Claude Code from any project:

```bash
claude
```

Inside Claude Code, run:

```text
/mcp
```

## Codex

Install and register GovData MCP for Codex:

```bash
python3 install.py --codex
```

Verify the registration:

```bash
codex mcp list
codex mcp get govdata
```

Start Codex from any project:

```bash
codex
```

Inside Codex, run:

```text
/mcp
```

## MCP Tools

GovData MCP exposes a compact tool profile by default:

```text
govdata_query
govdata_find_dataset
govdata_get_dataset
govdata_guidance
govdata_auth_status
```

Start with `govdata_query` for most data questions. It resolves likely
agencies and endpoints inside the MCP server, then executes only when the route
is confident and complete.

Use `govdata_find_dataset` for dataset discovery, source comparison, metadata,
and extract planning. Use `govdata_get_dataset` for saved responses, extract
creation, status checks, polling, and downloads.

Common resources:

```text
govdata://guide
govdata://auth/status
govdata://agencies
govdata://agency/{agency_id}/docs
govdata://endpoint/{agency_id}/{endpoint_id}/docs
govdata://endpoint/{agency_id}/{endpoint_id}/examples
```

Set `GOVDATA_TOOL_PROFILE=full` before starting `govdata-mcp` to expose direct
registry and endpoint tools:

```text
govdata_list_agencies
govdata_describe_agency
govdata_explain_endpoint
govdata_request
govdata_agency_request
govdata_download_plan
govdata_search_catalog
```

The checked-in `.mcp.json` uses the installed command:

```json
{
  "mcpServers": {
    "govdata": {
      "command": "govdata-mcp"
    }
  }
}
```

## Auth

GovData MCP reads API keys from environment variables or from its local
persisted auth store. Configure keys interactively:

```bash
govdata-auth setup
```

Inspect configured key names without exposing values:

```bash
govdata-auth list
govdata-auth path
```

Set or delete a single key:

```bash
govdata-auth set API_DATA_GOV_KEY
govdata-auth delete API_DATA_GOV_KEY
```

Supported key names:

```text
API_DATA_GOV_KEY
CENSUS_API_KEY
BLS_API_KEY
EIA_API_KEY
FDA_API_KEY
FRED_API_KEY
IPUMS_API_KEY
NREL_API_KEY
GOVDATA_ALLOW_DEMO_KEY
```

Do not put API keys in `.mcp.json`, prompts, examples, logs, or checked-in
files. Environment variables override persisted keyring or file values.

## Supported Data Sources

GovData MCP currently covers federal APIs and adjacent public data services
commonly used for policy, economics, public health, law, environment, science,
and social science research.

### Shared api.data.gov Key

Use `API_DATA_GOV_KEY` for participating federal APIs:

- Department of Agriculture - FoodData Central foods, food details, and food search
- Department of Commerce - news, blog posts, and image metadata
- Department of Education - College Scorecard schools and fields of study
- Department of Justice - FBI crime data, BJS NCVS, CrimeSolutions, and FARA
- Energy Information Administration - EIA v2 data, metadata, and legacy series lookup
- Federal Election Commission - candidates, committees, filings, elections, receipts, and disbursements
- Federal Trade Commission - Do Not Call complaints and HSR early termination notices
- Food and Drug Administration - openFDA drug, device, and food event/enforcement data
- Government Publishing Office - govinfo collections, packages, granules, and search
- Library of Congress - Congress.gov bills, members, committees, hearings, and nominations
- National Renewable Energy Laboratory - alternative fuel stations and PVWatts

### Dedicated Keys

- Census - dataset discovery, variables, geography metadata, and tabular data with `CENSUS_API_KEY`
- BLS - labor statistics time series and survey metadata with `BLS_API_KEY`
- FRED - Federal Reserve series, observations, categories, releases, and metadata with `FRED_API_KEY`
- IPUMS - harmonized microdata, aggregate, spatial, metadata, extract, and download workflows with `IPUMS_API_KEY`

### Public Sources

These sources do not require a per-user key for ordinary use:

- Data.gov Catalog - dataset search, organizations, and keywords
- USAspending.gov - federal award search, agencies, spending categories, and update metadata
- Department of Treasury Fiscal Data - public debt and exchange rates
- Environmental Protection Agency ECHO - regulated facilities and facility reports
- Federal Communications Commission - census block and geographic lookups
- Federal Deposit Insurance Corporation BankFind - institutions, branches, financials, summaries, and failures
- General Services Administration - API directory
- National Institutes of Health RePORTER - funded research projects and linked publications
- Data USA - aggregated demographic and economic indicators

## Saving Data

Responses include source metadata such as agency ID, endpoint ID, URL, docs URL,
query or body details, HTTP status, and retrieval time. Use `save_to_disk=true`
with `govdata_query` or `govdata_request` to save API responses under:

```text
data/govdata-downloads/responses
```

IPUMS downloads are saved under:

```text
data/govdata-downloads/ipums
```

Saved files include byte counts and SHA-256 hashes when available.

## Troubleshooting

Check that the package imports:

```bash
uv run python -c "import govdata_mcp.server; print('ok')"
```

Check installed commands:

```bash
command -v govdata-mcp
command -v govdata-auth
```

Check saved keys:

```bash
govdata-auth list
govdata-auth path
```

If Claude Code or Codex cannot see the server, re-register it:

```bash
python3 install.py --all --force-reinstall
```

If an endpoint reports a missing key, add the key with `govdata-auth setup` and
restart the MCP client session.

If an API returns `403`, check that the key is valid for that provider and that
the request is using the expected auth location. If an API returns `429`, wait
and retry with a smaller request; some upstream services enforce strict request
spacing.

For a dry run of installer changes:

```bash
python3 install.py --dry-run --all --no-verify
```

## Development

Install development dependencies and run tests:

```bash
uv sync --dev
uv run pytest
```

Build the package:

```bash
uv build
```

The package name is `govdata-mcp`, the server command is `govdata-mcp`, and the
registered MCP server name is `govdata`.

## License

Apache License 2.0. See `LICENSE`.
