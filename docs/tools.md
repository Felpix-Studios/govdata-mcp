# Tools

GovData MCP has two tool profiles. Compact mode is the default and is intended
for normal use. Full mode exposes lower-level direct endpoint helpers for
debugging and advanced workflows.

## Compact Tools

### `govdata_query`

Use for most data questions. It plans a route from natural language, optional
`source_hint`, optional `route_id`, and structured `path_params`, `query`, or
`body` inputs. It executes only when the route is confident and complete.

Typical uses:

```text
govdata_query(request="Search Data.gov for poverty datasets", source_hint="datagov", limit=3)
govdata_query(request="Fetch FRED GDP observations from 2020 through 2025", source_hint="fred")
govdata_query(request="2023 ACS5 total population by state", source_hint="census")
govdata_query(route_id="census.data", path_params={"year":2023,"dataset":"acs/acs5"}, query={"get":"NAME,B01003_001E","for":"state:*"})
```

Use `save_to_disk=true` when a user asks to save an ordinary API response.

### `govdata_find_dataset`

Use for read-only discovery and planning. Supported actions include `plan`,
`search`, `describe`, `metadata`, `compare`, and `examples`.

Typical uses:

```text
govdata_find_dataset(action="plan", request="Download ACS PUMS microdata for California with AGE, SEX, and INCTOT")
govdata_find_dataset(action="describe", source_hint="ipums", collection="usa")
govdata_find_dataset(action="metadata", agency_id="census", query={"year":2023,"dataset":"acs/acs5","metadata":"variables"})
```

### `govdata_get_dataset`

Use for acquisition and side effects: saving API responses, creating IPUMS
extracts, checking extract status, polling, and downloading files.

Typical uses:

```text
govdata_get_dataset(action="save_response", agency_id="census", endpoint_id="variables", path_params={"year":2023,"dataset":"acs/acs5"}, output_dir="data/govdata-downloads/responses", filename="acs5_2023_variables.json")
govdata_get_dataset(action="create_extract", source="ipums", collection="cps", extract={"description":"Small CPS smoke test","dataStructure":{"rectangular":{"on":"P"}},"dataFormat":"csv","samples":{"cps2019_03s":{}},"variables":{"AGE":{},"SEX":{},"RACE":{},"STATEFIP":{}}})
govdata_get_dataset(action="download_extract", source="ipums", collection="cps", extract_number=<returned_extract_number>)
```

`govdata_find_dataset` is read-only. `govdata_get_dataset` may create remote jobs,
poll status, and write files.

### `govdata_guidance`

Use for built-in workflow help. Topics are:

```text
overview
workflow
datasets
agency_notes
examples
auth
all
```

### `govdata_auth_status`

Use to inspect configured auth readiness without exposing secret values. Pass
`include_endpoints=true` for endpoint-level readiness.

## Full-Mode Tools

Set `GOVDATA_TOOL_PROFILE=full` before starting `govdata-mcp`.

```text
govdata_list_agencies
govdata_describe_agency
govdata_explain_endpoint
govdata_request
govdata_agency_request
govdata_download_plan
govdata_search_catalog
```

Use `govdata_request` for a known allowlisted endpoint. Use
`govdata_agency_request` only when no canonical endpoint exists and the agency
passthrough policy allows the path.

## Resources

```text
govdata://guide
govdata://guide/workflow
govdata://guide/agency-notes
govdata://guide/examples
govdata://auth
govdata://auth/status
govdata://agencies
govdata://agency/{agency_id}/docs
govdata://endpoint/{agency_id}/{endpoint_id}/docs
govdata://endpoint/{agency_id}/{endpoint_id}/parameters
govdata://endpoint/{agency_id}/{endpoint_id}/examples
```

Resources are the best way to inspect current registry, docs, auth, parameters,
and examples from inside an MCP client.

## Prompts

GovData also exposes reusable MCP prompts:

```text
govdata_research
govdata_smoke_test
```

Use `govdata_research` to guide an agent through a data lookup with source
metadata preservation. Use `govdata_smoke_test` for a short no-key health check.

## Response Handling

Responses preserve source metadata when available:

- agency ID and endpoint ID
- source URL and docs URL
- request path params, query, and body
- HTTP status and retrieval time
- saved path, byte count, and SHA-256 hash for saved artifacts

Large, binary, streamed, or attachment-like responses are saved rather than
returned inline through MCP.
