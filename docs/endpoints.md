# Endpoints And Data Sources

GovData MCP keeps an allowlisted registry of agencies and endpoints in
`src/govdata_mcp/registry.py`. The current registry has 29 active agencies and
110 active endpoints.

For live endpoint details from an MCP client, prefer resources over static docs:

```text
govdata://agencies
govdata://agency/{agency_id}/docs
govdata://endpoint/{agency_id}/{endpoint_id}/docs
govdata://endpoint/{agency_id}/{endpoint_id}/parameters
govdata://endpoint/{agency_id}/{endpoint_id}/examples
```

## Default Workflow

Start with `govdata_query` for ordinary data questions. It resolves likely
agencies and endpoints inside the server, then executes only when the route is
confident and complete.

Use `govdata_find_dataset` for discovery, source comparison, metadata, and
extract planning. Use `govdata_get_dataset` for saved responses, extract jobs,
status checks, polling, and downloads.

## Auth Boundary Groups

### Shared `API_DATA_GOV_KEY`

- `agriculture` - FoodData Central food detail, batch detail, lists, and search.
- `commerce` - Commerce.gov news, blog, and image metadata.
- `education` - College Scorecard schools and fields of study.
- `justice` - FBI Crime Data agency and offense summaries.
- `justice_crimesolutions` - rated criminal justice programs and practices.
- `justice_ncvs` - BJS National Crime Victimization Survey records.
- `eia` - EIA v2 metadata/data and legacy series lookup; can also use `EIA_API_KEY`.
- `fec` - candidates, committees, filings, elections, receipts, and disbursements.
- `ftc` - Do Not Call complaints and HSR early termination notices.
- `fda` - openFDA drug, device, and food event/enforcement records; can also use `FDA_API_KEY`.
- `govinfo` - GPO collections, package summaries, granules, and search.
- `loc` - Congress.gov bills, members, committees, hearings, and nominations.
- `nrel` - alternative fuel stations and PVWatts; can also use `NREL_API_KEY`.

### Dedicated Keys

- `census` - dataset discovery, variables, geography metadata, and tabular data with `CENSUS_API_KEY`.
- `bls` - labor time series and survey metadata, with `BLS_API_KEY` for registered access.
- `fred` - FRED search, metadata, observations, categories, releases, and release observations with `FRED_API_KEY`.
- `ipums` - IPUMS metadata, extract creation, extract status, downloads, and supplemental data with `IPUMS_API_KEY`.

### No Key For Ordinary Use

- `datagov` - Data.gov dataset catalog search, organizations, and keywords.
- `datausa` - Data USA Tesseract data and cube discovery.
- `epa` - ECHO CWA facilities and facility reports.
- `fcc` - census block and area lookup.
- `fdic` - BankFind institutions, locations, financials, summaries, and failures.
- `gsa` - GSA API directory.
- `justice_fara` - FARA registrants, documents, forms, and foreign principals.
- `nih` and `nih_reporter` - NIH RePORTER project search and publications.
- `treasury` and `treasury_fiscaldata` - Fiscal Data debt and exchange-rate data.
- `usaspending` - federal award search, agencies, spending category summaries, and data freshness.

## Known Endpoint Notes

- EPA `all_media_facilities` is marked stale because the provider route returns 404. Use `epa.cwa_facilities` or `epa.facility_report` instead.
- FARA and NIH RePORTER calls are rate-gated by the MCP at 3 seconds between requests.
- IPUMS extracts are asynchronous. Create an extract, keep the returned number, then poll and download through `govdata_get_dataset`.
- Large, binary, streamed, or attachment-like responses are saved under `data/govdata-downloads/responses` instead of being returned inline.
- Response envelopes include source metadata: agency ID, endpoint ID, source URL, docs URL, request path/query/body, status code, and retrieval time.

## Full Tool Profile

Set `GOVDATA_TOOL_PROFILE=full` before starting the server to expose direct
GovData-named tools such as:

```text
govdata_list_agencies
govdata_describe_agency
govdata_explain_endpoint
govdata_request
govdata_agency_request
govdata_download_plan
govdata_search_catalog
```

Full mode still exposes `govdata_*` tools only. It does not expose legacy
provider-specific tool names such as `ipums_*`, `fred_*`, or `census_*`.
