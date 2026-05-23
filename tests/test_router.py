from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from govdata_mcp import server as server_module
from govdata_mcp.router import plan_data_request


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_default_tool_profile_is_compact() -> None:
    async def scenario() -> list[str]:
        tools = await server_module.mcp.list_tools()
        return [tool.name for tool in tools]

    assert server_module.TOOL_PROFILE == "compact"
    assert set(run(scenario())) == {
        "govdata_query",
        "govdata_find_dataset",
        "govdata_get_dataset",
        "govdata_guidance",
        "govdata_auth_status",
    }


def test_full_tool_profile_keeps_direct_tools_visible() -> None:
    script = """
import asyncio, json
from govdata_mcp.server import mcp, TOOL_PROFILE
async def main():
    tools = await mcp.list_tools()
    print(json.dumps({"profile": TOOL_PROFILE, "tools": [tool.name for tool in tools]}))
asyncio.run(main())
"""
    env = dict(os.environ)
    env["GOVDATA_TOOL_PROFILE"] = "full"
    source_path = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in [source_path, env.get("PYTHONPATH", "")] if value
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(result.stdout)

    assert payload["profile"] == "full"
    assert "govdata_query" in payload["tools"]
    assert "govdata_find_dataset" in payload["tools"]
    assert "govdata_get_dataset" in payload["tools"]
    assert "govdata_request" in payload["tools"]
    assert "govdata_agency_request" in payload["tools"]
    assert all(tool.startswith("govdata_") for tool in payload["tools"])
    assert not any(
        tool.startswith(("ipums_", "fred_", "census_", "bls_", "nih_", "usaspending_", "govinfo_", "commerce_", "datausa_"))
        for tool in payload["tools"]
    )


def test_router_plans_fred_observations() -> None:
    payload = plan_data_request(
        "Fetch FRED GDP observations from 2020 through 2025",
        source_hint="fred",
    )

    assert payload["status"] == "planned"
    selected = payload["selected_route"]
    assert selected["route_id"] == "fred.series_observations"
    assert selected["query"]["series_id"] == "GDP"
    assert selected["query"]["observation_start"] == "2020-01-01"
    assert selected["query"]["observation_end"] == "2025-12-31"


def test_router_plans_datagov_catalog_search() -> None:
    payload = plan_data_request(
        "Search Data.gov for poverty datasets",
        source_hint="datagov",
        limit=3,
    )

    assert payload["status"] == "planned"
    selected = payload["selected_route"]
    assert selected["route_id"] == "datagov.search"
    assert selected["query"] == {"q": "poverty", "per_page": 3}


def test_router_plans_census_acs_data() -> None:
    payload = plan_data_request(
        "2023 ACS5 total population by state",
        source_hint="census",
    )

    assert payload["status"] == "planned"
    selected = payload["selected_route"]
    assert selected["route_id"] == "census.data"
    assert selected["path_params"] == {"year": 2023, "dataset": "acs/acs5"}
    assert selected["query"] == {"get": "NAME,B01003_001E", "for": "state:*"}


def test_router_uses_download_plan_for_ipums_extract_requests() -> None:
    payload = plan_data_request("Download ACS PUMS microdata for California")

    assert payload["status"] == "planned"
    assert payload["selected_route"]["route_id"] == "govdata.download_plan"
    assert payload["selected_route"]["action"] == "download_plan"


def test_router_reports_ambiguous_cpi_request() -> None:
    payload = plan_data_request("Fetch CPI data")

    assert payload["status"] == "ambiguous"
    assert {candidate["route_id"] for candidate in payload["candidates"]} >= {
        "bls.timeseries",
        "fred.series_search",
    }


def test_router_plans_fbi_cde_summarized_state_request() -> None:
    payload = plan_data_request(
        "Fetch FBI Crime Data Explorer violent crime summary for California from 2020 through 2021",
        source_hint="justice",
    )

    assert payload["status"] == "planned"
    selected = payload["selected_route"]
    assert selected["route_id"] == "justice.summarized_state"
    assert selected["path_params"] == {"state_abbr": "CA", "offense": "violent-crime"}
    assert selected["query"] == {"from": "01-2020", "to": "12-2021"}


def test_router_plans_ncvs_household_population_request() -> None:
    payload = plan_data_request(
        "Get NCVS household population records for 2022",
        source_hint="justice_ncvs",
        limit=5,
    )

    assert payload["status"] == "planned"
    selected = payload["selected_route"]
    assert selected["route_id"] == "justice_ncvs.household_population"
    assert selected["query"] == {"$limit": 5, "year": 2022}


def test_router_plans_crimesolutions_practice_request() -> None:
    payload = plan_data_request(
        "Find effective CrimeSolutions practices",
        source_hint="justice_crimesolutions",
    )

    assert payload["status"] == "planned"
    selected = payload["selected_route"]
    assert selected["route_id"] == "justice_crimesolutions.practices"
    assert selected["query"] == {"practice_evidence_rating": "Effective"}


def test_explicit_route_normalizes_known_manual_test_request_shapes() -> None:
    spending = plan_data_request(
        "Search USAspending awards",
        route_id="usaspending.search_spending_by_award",
        body={
            "filters": {"keywords": ["community health"]},
            "fields": ["Award ID"],
            "page": 1,
            "limit": 5,
        },
    )
    assert spending["status"] == "planned"
    assert "award_type_codes" not in spending["selected_route"]["body"]["filters"]

    category_spending = plan_data_request(
        "Search USAspending spending by category",
        route_id="usaspending.search_spending_by_category",
        body={
            "category": "awarding_agency",
            "filters": {"time_period": [{"start_date": "2024-10-01", "end_date": "2025-09-30"}]},
            "limit": 5,
        },
    )
    assert category_spending["status"] == "planned"
    assert category_spending["selected_route"]["path_params"] == {"category": "awarding_agency"}
    assert "category" not in category_spending["selected_route"]["body"]
    assert any(record["code"] == "request_shape_normalized" for record in category_spending["diagnostics"])

    mixed_spending = plan_data_request(
        "Search USAspending awards",
        route_id="usaspending.search_spending_by_award",
        body={
            "filters": {"award_type_codes": ["A", "02"]},
            "fields": ["Award ID"],
            "page": 1,
            "limit": 5,
        },
    )
    assert mixed_spending["status"] == "needs_input"
    assert "cannot mix contract and assistance groups" in mixed_spending["warnings"][0]

    govinfo = plan_data_request(
        "Search govinfo",
        route_id="govinfo.search",
        body={"query": "housing affordability", "pageSize": 5},
    )
    assert govinfo["selected_route"]["body"]["offsetMark"] == "*"

    ftc = plan_data_request(
        "HSR notices",
        route_id="ftc.hsr_early_termination_notices",
        query={"limit": 5},
    )
    assert ftc["status"] == "planned"
    assert ftc["selected_route"].get("query") is None or ftc["selected_route"]["query"] == {}

    crimesolutions = plan_data_request(
        "CrimeSolutions programs",
        route_id="justice_crimesolutions.programs",
        query={"$limit": 5},
    )
    assert crimesolutions["selected_route"].get("query") is None or crimesolutions["selected_route"]["query"] == {}

    commerce = plan_data_request(
        "Commerce image manufacturing",
        route_id="commerce.image",
        query={"filter[title]": "manufacturing", "page[limit]": 5},
    )
    assert commerce["status"] == "planned"
    assert commerce["selected_route"]["query"]["q"] == "manufacturing"
    assert "filter[title]" not in commerce["selected_route"]["query"]

    education = plan_data_request(
        "Education four-year schools",
        route_id="education.schools",
        query={"latest.academics.program_available.bachelors": True, "school.ownership": 1},
    )
    assert education["status"] == "planned"
    assert education["selected_route"]["query"]["school.degrees_awarded.predominant"] == 3
    assert "latest.academics.program_available.bachelors" not in education["selected_route"]["query"]


def test_explicit_nrel_location_only_request_needs_coordinates_or_zip() -> None:
    payload = plan_data_request(
        "Find stations by address",
        route_id="nrel.alt_fuel_nearest",
        query={"location": "1600 Pennsylvania Ave NW, Washington, DC", "fuel_type": "ELEC"},
    )

    assert payload["status"] == "needs_input"
    assert "latitude/longitude or zip" in payload["warnings"][0]


def test_explicit_fec_senate_elections_need_state() -> None:
    missing_state = plan_data_request(
        "FEC Senate elections",
        route_id="fec.elections",
        query={"cycle": 2024, "office": "senate", "per_page": 5},
    )

    assert missing_state["status"] == "needs_input"
    assert "query.state" in missing_state["warnings"][0]

    with_state = plan_data_request(
        "FEC California Senate elections",
        route_id="fec.elections",
        query={"cycle": 2024, "office": "senate", "state": "CA", "per_page": 5},
    )

    assert with_state["status"] == "planned"
    assert with_state["selected_route"]["query"]["state"] == "CA"


def test_explicit_stale_endpoint_is_not_planned_for_execution() -> None:
    payload = plan_data_request(
        "EPA all-media facilities",
        route_id="epa.all_media_facilities",
        query={"p_st": "LA", "responseset": 5, "output": "JSON"},
    )

    assert payload["status"] == "needs_input"
    assert "Endpoint epa.all_media_facilities is stale" in payload["warnings"][0]


def test_explicit_datausa_legacy_population_request_is_mapped_to_tesseract() -> None:
    payload = plan_data_request(
        "Data USA population by state",
        route_id="datausa.data",
        query={"Geography": "04000US06", "measure": "Population", "drilldowns": "State"},
    )

    assert payload["status"] == "planned"
    selected = payload["selected_route"]
    assert selected["query"]["cube"] == "acs_yg_total_population_5"
    assert selected["query"]["measures"] == "Population"
    assert selected["query"]["include"] == "State:04000US06"


def test_explicit_datausa_occupation_drilldown_is_mapped_to_supported_level() -> None:
    payload = plan_data_request(
        "Data USA occupation workforce in California",
        route_id="datausa.data",
        query={
            "cube": "acs_ygso_gender_by_occupation_c_5",
            "drilldowns": "ACS Occupation,Year",
            "measures": "Workforce by Occupation and Gender",
            "include": "State:04000US06,Year:2023",
            "limit": "5,0",
        },
    )

    assert payload["status"] == "planned"
    assert payload["selected_route"]["query"]["drilldowns"] == "Occupation,Year"
    assert payload["selected_route"]["query"]["State"] == "04000US06"
    assert payload["selected_route"]["query"]["include"] == "Year:2023"
    assert any(record["code"] == "request_shape_normalized" for record in payload["diagnostics"])


def test_govdata_find_dataset_examples_action_returns_endpoint_examples() -> None:
    payload = run(
        server_module.govdata_find_dataset(
            action="examples",
            agency_id="commerce",
            endpoint_id="image",
        )
    )

    assert payload["status"] == "executed"
    assert payload["action"] == "examples"
    assert payload["source"] == "commerce"
    assert payload["result"]["endpoint"]["id"] == "image"
    assert len(payload["result"]["examples"]) == 3


def test_router_plans_fara_requests_and_missing_registration_number() -> None:
    payload = plan_data_request("List active FARA registrants", source_hint="justice_fara")

    assert payload["status"] == "planned"
    assert payload["selected_route"]["route_id"] == "justice_fara.registrants_active"

    missing = plan_data_request("List FARA foreign principals", source_hint="justice_fara")

    assert missing["status"] == "needs_input"
    assert missing["selected_route"]["route_id"] == "justice_fara.foreign_principals_active"
    assert missing["warnings"] == ["Missing required inputs: registration_number."]


def test_govdata_query_executes_mocked_selected_route(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_request_raw(
        agency_id: str,
        endpoint_id: str,
        *,
        path_params: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        save_response: bool = False,
        output_dir: str | None = None,
        filename: str | None = None,
        max_inline_bytes: int | None = None,
    ) -> dict[str, Any]:
        calls.append(
            {
                "agency_id": agency_id,
                "endpoint_id": endpoint_id,
                "path_params": path_params,
                "query": query,
                "body": body,
                "save_response": save_response,
                "output_dir": output_dir,
                "filename": filename,
                "max_inline_bytes": max_inline_bytes,
            }
        )
        return {
            "agency_id": agency_id,
            "endpoint_id": endpoint_id,
            "status_code": 200,
            "raw": {"ok": True},
        }

    monkeypatch.setattr(server_module, "request_raw", fake_request_raw)

    payload = run(
        server_module.govdata_query(
            "Search Data.gov for poverty datasets",
            source_hint="datagov",
            limit=3,
        )
    )

    assert payload["status"] == "executed"
    assert payload["result"]["raw"] == {"ok": True}
    assert payload["classification"] == "PASS"
    assert calls == [
        {
            "agency_id": "datagov",
            "endpoint_id": "search",
            "path_params": None,
            "query": {"q": "poverty", "per_page": 3},
            "body": None,
            "save_response": False,
            "output_dir": None,
            "filename": None,
            "max_inline_bytes": None,
        }
    ]


def test_govdata_query_returns_structured_error_for_blank_exception(monkeypatch: Any) -> None:
    async def fake_request_raw(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise Exception()

    monkeypatch.setattr(server_module, "request_raw", fake_request_raw)

    payload = run(
        server_module.govdata_query(
            "Search Data.gov for poverty datasets",
            source_hint="datagov",
        )
    )

    assert payload["status"] == "error"
    assert payload["warnings"] == ["execute failed with Exception: Exception"]
    assert payload["error"]["type"] == "Exception"
    assert payload["error"]["message"] == "Exception"


def test_govdata_query_can_save_selected_route_to_disk(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_request_raw(
        agency_id: str,
        endpoint_id: str,
        *,
        path_params: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        save_response: bool = False,
        output_dir: str | None = None,
        filename: str | None = None,
        max_inline_bytes: int | None = None,
    ) -> dict[str, Any]:
        calls.append(
            {
                "agency_id": agency_id,
                "endpoint_id": endpoint_id,
                "save_response": save_response,
                "output_dir": output_dir,
                "filename": filename,
                "max_inline_bytes": max_inline_bytes,
            }
        )
        return {
            "agency_id": agency_id,
            "endpoint_id": endpoint_id,
            "status_code": 200,
            "download": {"saved": True, "path": "/workspace/data/acs5_variables.json"},
            "raw": {"_govdata_response_saved": True},
        }

    monkeypatch.setattr(server_module, "request_raw", fake_request_raw)

    payload = run(
        server_module.govdata_query(
            "Download 2023 ACS5 variables metadata",
            route_id="census.variables",
            path_params={"year": 2023, "dataset": "acs/acs5"},
            save_to_disk=True,
            filename="acs5_variables.json",
            max_inline_bytes=10,
        )
    )

    assert payload["status"] == "executed"
    assert payload["result"]["download"]["saved"] is True
    assert payload["classification"] == "PASS"
    assert payload["saved_artifacts"] == [{"saved": True, "path": "/workspace/data/acs5_variables.json"}]
    assert calls == [
        {
            "agency_id": "census",
            "endpoint_id": "variables",
            "save_response": True,
            "output_dir": None,
            "filename": "acs5_variables.json",
            "max_inline_bytes": 10,
        }
    ]


def test_govdata_query_promotes_agent_fields_from_result(monkeypatch: Any) -> None:
    async def fake_request_raw(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "agency_id": "ftc",
            "endpoint_id": "dnc_complaints",
            "status_code": 200,
            "classification": "PASS_WITH_WARNING",
            "diagnostics": [
                {
                    "code": "provider_limit_ignored",
                    "severity": "warning",
                    "message": "Provider returned more records than requested by the bounded limit.",
                }
            ],
            "requested_limit": 5,
            "record_count": 50,
            "returned_count": 50,
            "bounded_preview": {"results": [{"id": item} for item in range(5)]},
            "agent_next_actions": ["Use bounded_preview for the requested row count."],
            "raw": {"results": [{"id": item} for item in range(50)]},
        }

    monkeypatch.setattr(server_module, "request_raw", fake_request_raw)

    payload = run(
        server_module.govdata_query(
            "Get FTC Do Not Call complaints",
            route_id="ftc.dnc_complaints",
            query={"limit": 5},
        )
    )

    assert payload["status"] == "executed"
    assert payload["classification"] == "PASS_WITH_WARNING"
    assert payload["requested_limit"] == 5
    assert payload["record_count"] == 50
    assert len(payload["bounded_preview"]["results"]) == 5
    assert any(record["code"] == "provider_limit_ignored" for record in payload["diagnostics"])
    assert payload["agent_next_actions"] == ["Use bounded_preview for the requested row count."]


def test_info_only_request_shape_diagnostics_do_not_create_warning_classification(monkeypatch: Any) -> None:
    async def fake_request_raw(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "agency_id": "datausa",
            "endpoint_id": "data",
            "status_code": 200,
            "classification": "PASS",
            "diagnostics": [],
            "raw": {"data": [{"id": "1"}]},
        }

    monkeypatch.setattr(server_module, "request_raw", fake_request_raw)

    payload = run(
        server_module.govdata_query(
            "Data USA occupation workforce in California",
            route_id="datausa.data",
            query={
                "cube": "acs_ygso_gender_by_occupation_c_5",
                "drilldowns": "ACS Occupation,Year",
                "measures": "Workforce by Occupation and Gender",
                "include": "State:04000US06,Year:2023",
                "limit": "5,0",
            },
        )
    )

    assert payload["status"] == "executed"
    assert payload["classification"] == "PASS"
    assert any(
        record["code"] == "request_shape_normalized" and record["severity"] == "info"
        for record in payload["diagnostics"]
    )
