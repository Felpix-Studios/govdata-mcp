from govdata_mcp.registry import AGENCIES, get_agency, list_agencies


def test_core_agencies_are_active() -> None:
    active_ids = {agency["id"] for agency in list_agencies(include_planned=False)}

    assert {
        "datagov",
        "census",
        "bls",
        "nih_reporter",
        "usaspending",
        "govinfo",
        "gsa",
        "commerce",
        "datausa",
    }.issubset(active_ids)


def test_requested_api_data_gov_agencies_and_fred_are_active() -> None:
    active_ids = {agency["id"] for agency in list_agencies(include_planned=False)}

    assert {
        "agriculture",
        "commerce",
        "education",
        "justice",
        "justice_crimesolutions",
        "justice_fara",
        "justice_ncvs",
        "treasury",
        "eia",
        "epa",
        "fcc",
        "fdic",
        "fec",
        "ftc",
        "fda",
        "gsa",
        "govinfo",
        "loc",
        "nih",
        "nrel",
        "fred",
        "ipums",
    }.issubset(active_ids)


def test_openfda_duplicate_alias_is_not_registered() -> None:
    active_ids = {agency["id"] for agency in list_agencies(include_planned=False)}

    assert "fda" in active_ids
    assert "openfda" not in active_ids
    assert "openfda" not in AGENCIES


def test_api_data_gov_registry_drift_fixes_are_encoded() -> None:
    assert "options" not in AGENCIES["commerce"].endpoints
    assert AGENCIES["education"].endpoints["fields_of_study"].path == "/schools"
    assert AGENCIES["justice"].base_url == "https://api.usa.gov/crime/fbi/cde"
    assert AGENCIES["justice"].endpoints["agencies"].path == "/agency/byStateAbbr/{state_abbr}"
    assert AGENCIES["justice"].endpoints["agencies"].auth_name == "API_KEY"
    assert AGENCIES["justice"].endpoints["summarized_national"].path == "/summarized/national/{offense}"
    assert AGENCIES["justice"].endpoints["summarized_state"].path == "/summarized/state/{state_abbr}/{offense}"
    assert AGENCIES["justice"].endpoints["summarized_agency"].path == "/summarized/agency/{ori}/{offense}"
    assert AGENCIES["fec"].endpoints["elections"].path == "/elections/"
    assert "president, senate, or house" in AGENCIES["fec"].endpoints["elections"].description

    loc = AGENCIES["loc"]
    assert loc.base_url == "https://api.congress.gov/v3"
    assert "v3 API" in loc.description
    assert loc.default_auth == "api_data_gov"
    assert loc.default_auth_location == "header"
    assert loc.default_auth_name == "x-api-key"
    for endpoint in loc.endpoints.values():
        assert endpoint.auth == "api_data_gov"
        assert endpoint.auth_location == "header"
        assert endpoint.auth_name == "x-api-key"
        assert endpoint.default_query["format"] == "json"


def test_doj_public_api_registries_use_shared_header_key_where_needed() -> None:
    ncvs = AGENCIES["justice_ncvs"]
    crimesolutions = AGENCIES["justice_crimesolutions"]
    fara = AGENCIES["justice_fara"]

    assert ncvs.base_url == "https://api.ojp.gov/bjsdataset/v1"
    assert {"personal_victimization", "personal_population", "household_victimization", "household_population"} <= set(ncvs.endpoints)
    assert {"programs", "practices"} <= set(crimesolutions.endpoints)
    assert crimesolutions.endpoints["programs"].default_query == {"all": ""}
    assert {"registrants_active", "registrants_new", "registration_documents"} <= set(fara.endpoints)
    assert fara.min_seconds_between_requests == 3.0

    for agency in (ncvs, crimesolutions):
        assert agency.default_auth == "api_data_gov"
        assert agency.default_auth_location == "header"
        assert agency.default_auth_name == "X-Api-Key"
        for endpoint in agency.endpoints.values():
            assert endpoint.auth == "api_data_gov"
            assert endpoint.auth_location == "header"
            assert endpoint.auth_name == "X-Api-Key"

    assert fara.default_auth == "none"
    assert all(endpoint.auth == "none" for endpoint in fara.endpoints.values())


def test_manual_test_registry_url_updates_are_encoded() -> None:
    assert AGENCIES["fdic"].base_url == "https://api.fdic.gov/banks"
    assert AGENCIES["epa"].base_url == "https://echodata.epa.gov/echo"
    assert AGENCIES["epa"].endpoints["all_media_facilities"].status == "stale"
    assert "404" in (AGENCIES["epa"].endpoints["all_media_facilities"].status_note or "")
    assert AGENCIES["epa"].endpoints["all_media_facilities"].alternatives == (
        "epa.cwa_facilities",
        "epa.facility_report",
    )
    assert AGENCIES["datausa"].base_url == "https://api.datausa.io/tesseract"
    assert AGENCIES["datausa"].endpoints["data"].path == "/data.jsonrecords"
    assert AGENCIES["datausa"].endpoints["search"].path == "/cubes"
    assert AGENCIES["usaspending"].endpoints["search_spending_by_category"].path == "/api/v2/search/spending_by_category/{category}/"
    assert AGENCIES["nrel"].base_url == "https://developer.nlr.gov/api"
    assert AGENCIES["nrel"].docs_url == "https://developer.nlr.gov/docs/"
    assert all("developer.nrel.gov" not in endpoint.docs_url for endpoint in AGENCIES["nrel"].endpoints.values())


def test_nih_reporter_rate_gate_uses_three_seconds() -> None:
    assert AGENCIES["nih"].min_seconds_between_requests == 3.0
    assert AGENCIES["nih_reporter"].min_seconds_between_requests == 3.0


def test_ipums_agency_supports_extract_collections_and_auth() -> None:
    ipums = AGENCIES["ipums"]

    assert ipums.status == "active"
    assert ipums.default_auth == "ipums"
    assert ipums.default_auth_location == "header"
    assert {
        "extracts",
        "extract",
        "create_extract",
        "metadata_datasets",
        "metadata_dataset",
        "metadata_data_tables",
        "metadata_shapefiles",
        "metadata_time_series_tables",
        "download",
        "supplemental_data",
    }.issubset(ipums.endpoints)


def test_get_agency_reports_unknown_id() -> None:
    try:
        get_agency("missing")
    except KeyError as exc:
        assert "Unknown agency_id" in str(exc)
    else:
        raise AssertionError("Expected KeyError")
