from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from govdata_mcp.client import SENSITIVE_KEYS
from govdata_mcp.endpoint_docs import (
    CANONICAL_AGENCY_IDS,
    ENDPOINT_DOCS,
    PATH_VAR_RE,
    agency_documentation_summary,
    canonical_endpoint_keys,
    endpoint_doc_payload,
    get_endpoint_doc,
)
from govdata_mcp.registry import AGENCIES
from govdata_mcp.server import (
    endpoint_docs_resource,
    endpoint_examples_resource,
    endpoint_parameters_resource,
    govdata_explain_endpoint,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_active_canonical_endpoints_have_docs_schema_and_three_examples() -> None:
    assert set(ENDPOINT_DOCS) == canonical_endpoint_keys()

    for agency_id, endpoint_id in canonical_endpoint_keys():
        doc = ENDPOINT_DOCS[(agency_id, endpoint_id)]

        assert doc.schema is not None
        assert len(doc.examples) == 3
        assert doc.official_docs_urls


def test_active_alias_endpoint_records_resolve_to_canonical_docs() -> None:
    for alias_id, canonical_id in CANONICAL_AGENCY_IDS.items():
        alias = AGENCIES[alias_id]
        canonical = AGENCIES[canonical_id]

        for endpoint_id in alias.endpoints:
            assert get_endpoint_doc(alias_id, endpoint_id) is get_endpoint_doc(canonical_id, endpoint_id)

        alias_doc_keys = {key for key in ENDPOINT_DOCS if key[0] == alias_id}
        assert alias_doc_keys == set()
        summary = agency_documentation_summary(alias_id)
        assert summary["canonical_agency_id"] == canonical_id
        assert len(summary["endpoints"]) == len(canonical.endpoints)
        assert all(endpoint["canonical_agency_id"] == canonical_id for endpoint in summary["endpoints"])


def test_alias_can_explain_canonical_endpoint_without_duplicate_doc_data() -> None:
    payload = endpoint_doc_payload("nih", "projects_search")

    assert payload["agency"]["id"] == "nih"
    assert payload["canonical_agency"]["id"] == "nih_reporter"
    assert payload["alias"]["canonical_agency_id"] == "nih_reporter"
    assert payload["endpoint"]["id"] == "projects_search"
    assert len(payload["examples"]) == 3


def test_path_parameters_cover_endpoint_placeholders_and_examples() -> None:
    for agency_id, endpoint_id in canonical_endpoint_keys():
        endpoint = AGENCIES[agency_id].endpoints[endpoint_id]
        placeholders = set(PATH_VAR_RE.findall(endpoint.path))
        doc = ENDPOINT_DOCS[(agency_id, endpoint_id)]

        schema_path_params = {parameter.name for parameter in doc.schema.path_parameters}
        assert placeholders <= schema_path_params

        for example in doc.examples:
            assert placeholders <= set(example.path_params)


def test_examples_are_json_serializable_and_omit_secret_like_auth_keys() -> None:
    secret_keys = {key.lower() for key in SENSITIVE_KEYS}

    for doc in ENDPOINT_DOCS.values():
        for example in doc.examples:
            json.dumps(example.to_dict())
            assert not _contains_secret_key(example.path_params, secret_keys)
            assert not _contains_secret_key(example.query, secret_keys)
            assert not _contains_secret_key(example.body, secret_keys)


def test_api_data_gov_endpoint_examples_match_known_drift_fixes() -> None:
    fec_elections = endpoint_doc_payload("fec", "elections")
    fec_query_names = {parameter["name"] for parameter in fec_elections["schema"]["query"]}
    fec_office_parameter = next(
        parameter
        for parameter in fec_elections["schema"]["query"]
        if parameter["name"] == "office"
    )
    fec_example_queries = [example["query"] for example in fec_elections["examples"]]

    assert {"cycle", "office", "election_full"} <= fec_query_names
    assert set(fec_office_parameter["enum"]) == {"president", "senate", "house"}
    assert "election_year" not in fec_query_names
    assert all({"cycle", "office"} <= set(query) for query in fec_example_queries)
    assert all("min_date" not in query and "max_date" not in query for query in fec_example_queries)
    assert {query["office"] for query in fec_example_queries} == {"president", "senate", "house"}
    assert all(query["office"] not in {"P", "S", "H"} for query in fec_example_queries)
    assert all(query.get("state") for query in fec_example_queries if query["office"] == "senate")
    assert all(
        query.get("state") and query.get("district")
        for query in fec_example_queries
        if query["office"] == "house"
    )

    ftc_hsr = endpoint_doc_payload("ftc", "hsr_early_termination_notices")
    assert ftc_hsr["schema"]["query"] == []
    assert all(example["query"] == {} for example in ftc_hsr["examples"])

    govinfo_collections = endpoint_doc_payload("govinfo", "collections")
    assert all(
        example["path_params"]["start_date"].endswith("Z")
        for example in govinfo_collections["examples"]
    )
    assert all(
        example["query"].get("offsetMark") == "*"
        for example in govinfo_collections["examples"]
    )

    education_fields = endpoint_doc_payload("education", "fields_of_study")
    assert all(
        example["query"].get("all_programs_nested") is True
        for example in education_fields["examples"]
    )

    fbi_summary = endpoint_doc_payload("justice", "summarized_state")
    assert {"state_abbr", "offense"} <= {parameter["name"] for parameter in fbi_summary["schema"]["path"]}
    assert {"from", "to"} <= {parameter["name"] for parameter in fbi_summary["schema"]["query"]}
    assert all(example["query"]["from"].count("-") == 1 for example in fbi_summary["examples"])

    ncvs = endpoint_doc_payload("justice_ncvs", "personal_population")
    assert ncvs["auth"]["location"] == "header"
    assert ncvs["auth"]["name"] == "X-Api-Key"
    assert "$limit" in {parameter["name"] for parameter in ncvs["schema"]["query"]}

    crimesolutions = endpoint_doc_payload("justice_crimesolutions", "programs")
    assert crimesolutions["endpoint"]["default_query"] == {"all": ""}
    assert any("CSV" in gotcha for gotcha in crimesolutions["common_gotchas"])

    fara = endpoint_doc_payload("justice_fara", "registrants_new")
    assert fara["auth"]["kind"] == "none"
    assert {parameter["name"] for parameter in fara["schema"]["query"]} == {"from", "to"}

    datausa = endpoint_doc_payload("datausa", "data")
    datausa_query_names = {parameter["name"] for parameter in datausa["schema"]["query"]}
    assert {"cube", "measures", "drilldowns"} <= datausa_query_names
    assert "measure" not in datausa_query_names

    usaspending_category = endpoint_doc_payload("usaspending", "search_spending_by_category")
    assert {parameter["name"] for parameter in usaspending_category["schema"]["path"]} == {"category"}
    assert "category" not in {parameter["name"] for parameter in usaspending_category["schema"]["body"]}
    assert all(example["path_params"].get("category") for example in usaspending_category["examples"])

    commerce_image = endpoint_doc_payload("commerce", "image")
    commerce_query_names = {parameter["name"] for parameter in commerce_image["schema"]["query"]}
    assert "q" in commerce_query_names
    assert "filter[title]" not in commerce_query_names
    assert all("filter[title]" not in example["query"] for example in commerce_image["examples"])

    education_schools = endpoint_doc_payload("education", "schools")
    assert "school.degrees_awarded.predominant" in {
        parameter["name"] for parameter in education_schools["schema"]["query"]
    }
    assert all(
        "latest.academics.program_available.bachelors" not in example["query"]
        for example in education_schools["examples"]
    )

    fda_device = endpoint_doc_payload("fda", "device_event")
    assert all("date_received" not in json.dumps(example["query"]) for example in fda_device["examples"])

    nrel = agency_documentation_summary("nrel")
    assert nrel["base_url"] == "https://developer.nlr.gov/api"
    assert "developer.nrel.gov" not in json.dumps(nrel)

    stale_epa = endpoint_doc_payload("epa", "all_media_facilities")
    assert stale_epa["endpoint"]["status"] == "stale"
    assert stale_epa["endpoint"]["alternatives"] == ["epa.cwa_facilities", "epa.facility_report"]
    assert stale_epa["schema"]["query"]
    assert len(stale_epa["examples"]) == 3


def test_explain_endpoint_tool_and_resources_serialize() -> None:
    tool_payload = run(govdata_explain_endpoint("fred", "series_observations"))
    assert tool_payload["endpoint"]["id"] == "series_observations"
    assert len(tool_payload["examples"]) == 3
    json.dumps(tool_payload)

    docs_payload = json.loads(endpoint_docs_resource("census", "data"))
    assert docs_payload["schema"]["query"]
    assert len(docs_payload["examples"]) == 3

    parameters_payload = json.loads(endpoint_parameters_resource("usaspending", "search_spending_by_award"))
    assert parameters_payload["schema"]["body"]
    assert "examples" not in parameters_payload

    examples_payload = json.loads(endpoint_examples_resource("nih", "projects_search"))
    assert examples_payload["canonical_agency"]["id"] == "nih_reporter"
    assert len(examples_payload["examples"]) == 3


def test_agency_docs_endpoint_summaries_include_doc_counts() -> None:
    summary = agency_documentation_summary("census")

    assert summary["endpoints"]
    for endpoint in summary["endpoints"]:
        assert endpoint["has_parameter_schema"] is True
        assert endpoint["example_count"] == 3
        assert "canonical_agency_id" not in endpoint


def test_agency_docs_surface_stale_endpoint_status_and_alternatives() -> None:
    summary = agency_documentation_summary("epa")
    all_media = next(endpoint for endpoint in summary["endpoints"] if endpoint["id"] == "all_media_facilities")

    assert all_media["status"] == "stale"
    assert "404" in all_media["status_note"]
    assert all_media["alternatives"] == ["epa.cwa_facilities", "epa.facility_report"]
    assert all_media["has_parameter_schema"] is True
    assert all_media["example_count"] == 3


def test_docs_do_not_reintroduce_known_stale_inputs() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    docs_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            repo_root / "docs" / "testing.md",
            repo_root / "docs" / "workflows.md",
            repo_root / "docs" / "tools.md",
        ]
    )

    stale_extract_placeholder = "extract number " + "12345"
    assert stale_extract_placeholder not in docs_text
    assert 'route_id="ftc.hsr_early_termination_notices", query={"limit":5}' not in docs_text
    assert 'route_id="nrel.alt_fuel_nearest", query={"location"' not in docs_text
    assert 'endpoint_id="programs", query={"$limit":5}' not in docs_text
    assert 'route_id="datausa.data", query={"Geography"' not in docs_text


def _contains_secret_key(value: Any, secret_keys: set[str]) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in secret_keys:
                return True
            if _contains_secret_key(item, secret_keys):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_key(item, secret_keys) for item in value)
    return False
