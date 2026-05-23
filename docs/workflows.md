# Workflows

These workflows are written for Claude Code, Codex, or another MCP client with
GovData MCP connected.

## General Data Lookup

1. Check auth readiness if the question may need a key:

   ```text
   govdata_auth_status(include_endpoints=true)
   ```

2. Ask GovData to plan and execute:

   ```text
   govdata_query(request="Search Data.gov for poverty datasets", source_hint="datagov", limit=3)
   ```

3. If the response is `needs_input` or `ambiguous`, provide the requested
   `route_id`, `source_hint`, `path_params`, `query`, or `body`.

4. Cite source metadata from the envelope: source URL, docs URL, status code,
   retrieved time, and request parameters.

## Data.gov Discovery

```text
govdata_find_dataset(action="search", source_hint="datagov", request="county-level eviction datasets", limit=5)
govdata_query(request="Search Data.gov for county-level eviction datasets", source_hint="datagov", limit=5)
```

Use catalog results to identify publisher, landing page, distributions, update
dates, and access level. Catalog search is discovery, not proof that every linked
distribution can be downloaded through GovData.

## Census ACS

Inspect metadata before fetching data unless exact variable and geography IDs
are supplied:

```text
govdata_find_dataset(action="metadata", agency_id="census", query={"year":2023,"dataset":"acs/acs5","metadata":"variables"})
govdata_query(route_id="census.data", path_params={"year":2023,"dataset":"acs/acs5"}, query={"get":"NAME,B01003_001E","for":"state:*"})
```

Distinguish estimates from margins of error, and keep variable IDs in the final
answer.

## BLS Time Series

```text
govdata_query(request="Fetch BLS series CUUR0000SA0 from 2020 through 2025")
```

Preserve series IDs, units, seasonality, and period codes. A `BLS_API_KEY` is
useful for registered limits but not always required for small requests.

## FRED Series

```text
govdata_query(request="Fetch FRED GDP observations from 2020 through 2025", source_hint="fred")
govdata_query(route_id="fred.series_observations", query={"series_id":"GDP","observation_start":"2020-01-01","observation_end":"2025-12-31","limit":100000})
```

Pin `route_id="fred.series_observations"` and set an explicit large `limit` when
you need full-history charting or want to avoid small routed defaults.

## USAspending

```text
govdata_query(request="When was USAspending award data last updated?", source_hint="usaspending")
govdata_query(route_id="usaspending.search_spending_by_award", body={"filters":{"time_period":[{"start_date":"2023-10-01","end_date":"2024-09-30"}],"keywords":["community health"],"award_type_codes":["A","B","C","D","02","03","04","05"]},"fields":["Award ID","Recipient Name","Award Amount","Awarding Agency"],"page":1,"limit":5})
```

Include award type and fiscal period assumptions in the answer.

## NIH RePORTER

```text
govdata_query(route_id="nih_reporter.projects_search", body={"criteria":{"fiscal_years":[2025]},"include_fields":["ApplId","ProjectTitle","AwardAmount"],"limit":50})
```

Keep `limit <= 500`, use `include_fields` to keep outputs compact, and let the
MCP rate gate space NIH calls by 3 seconds.

## Saving API Responses

Use either `save_to_disk=true` on `govdata_query` or
`govdata_get_dataset(action="save_response")`.

```text
govdata_query(route_id="census.variables", path_params={"year":2023,"dataset":"acs/acs5"}, save_to_disk=true)
govdata_get_dataset(action="save_response", agency_id="census", endpoint_id="variables", path_params={"year":2023,"dataset":"acs/acs5"}, output_dir="data/govdata-downloads/responses", filename="acs5_2023_variables.json")
```

Saved responses include file path, byte count, content type, and SHA-256 hash
when available.

## IPUMS Extracts

Plan first:

```text
govdata_find_dataset(action="plan", request="Download ACS PUMS microdata for California with AGE, SEX, and INCTOT")
govdata_find_dataset(action="describe", source_hint="ipums", collection="usa")
```

Create a small extract, then poll and download using the returned extract
number:

```text
govdata_get_dataset(action="create_extract", source="ipums", collection="cps", extract={"description":"Small CPS smoke test","dataStructure":{"rectangular":{"on":"P"}},"dataFormat":"csv","samples":{"cps2019_03s":{}},"variables":{"AGE":{},"SEX":{},"RACE":{},"STATEFIP":{}}})
govdata_get_dataset(action="get_extract", source="ipums", collection="cps", extract_number=<returned_extract_number>)
govdata_get_dataset(action="download_extract", source="ipums", collection="cps", extract_number=<returned_extract_number>)
```

Default IPUMS polling waits up to 1800 seconds, polling every 60 seconds for the
first 10 minutes and every 300 seconds after that. Prefer CSV extracts for
analysis unless the dataset is large enough that a zip bundle is more practical.

## Stale Or Guarded Routes

If a route is stale or missing required input, treat that as useful guard
behavior. For example, EPA `all_media_facilities` is marked stale and should be
replaced with `epa.cwa_facilities` or `epa.facility_report`. FEC Senate election
queries need a state. NREL nearest-station queries need coordinates or ZIP, not
a free-form `location` parameter.
