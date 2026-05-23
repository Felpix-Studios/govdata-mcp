from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from .registry import AGENCIES, AUTH_ENV, Agency, Endpoint, get_agency


ParameterLocation = Literal["path", "query", "body"]

CANONICAL_AGENCY_IDS: dict[str, str] = {
    "nih": "nih_reporter",
    "treasury_fiscaldata": "treasury",
}

PATH_VAR_RE = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)}")


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    location: ParameterLocation
    type: str
    required: bool = False
    default: Any | None = None
    enum: tuple[str, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None
    pattern: str | None = None
    repeatable: bool = False
    description: str = ""
    docs_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "location": self.location,
            "type": self.type,
            "required": self.required,
            "repeatable": self.repeatable,
            "description": self.description,
        }
        if self.default is not None:
            data["default"] = self.default
        if self.enum:
            data["enum"] = list(self.enum)
        if self.minimum is not None or self.maximum is not None:
            data["range"] = {
                key: value
                for key, value in {
                    "minimum": self.minimum,
                    "maximum": self.maximum,
                }.items()
                if value is not None
            }
        if self.pattern:
            data["pattern"] = self.pattern
        if self.docs_url:
            data["docs_url"] = self.docs_url
        return data


@dataclass(frozen=True)
class EndpointSchema:
    path_parameters: tuple[ParameterSpec, ...] = ()
    query_parameters: tuple[ParameterSpec, ...] = ()
    body_parameters: tuple[ParameterSpec, ...] = ()
    dynamic_fields: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": [parameter.to_dict() for parameter in self.path_parameters],
            "query": [parameter.to_dict() for parameter in self.query_parameters],
            "body": [parameter.to_dict() for parameter in self.body_parameters],
            "dynamic_fields": list(self.dynamic_fields),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class EndpointExample:
    title: str
    purpose: str
    path_params: dict[str, Any] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    expected_response_notes: str = ""
    data_source_variant: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "purpose": self.purpose,
            "path_params": self.path_params,
            "query": self.query,
            "body": self.body,
            "expected_response_notes": self.expected_response_notes,
            "data_source_variant": self.data_source_variant,
        }


@dataclass(frozen=True)
class EndpointDoc:
    schema: EndpointSchema
    examples: tuple[EndpointExample, EndpointExample, EndpointExample]
    common_gotchas: tuple[str, ...] = ()
    official_docs_urls: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema.to_dict(),
            "examples": [example.to_dict() for example in self.examples],
            "common_gotchas": list(self.common_gotchas),
            "official_docs_urls": list(self.official_docs_urls),
        }


def canonical_agency_id(agency_id: str) -> str:
    return CANONICAL_AGENCY_IDS.get(agency_id, agency_id)


def canonical_endpoint_keys() -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for agency in AGENCIES.values():
        if agency.status != "active" or agency.id in CANONICAL_AGENCY_IDS:
            continue
        for endpoint_id, endpoint in agency.endpoints.items():
            if endpoint.status == "active":
                keys.add((agency.id, endpoint_id))
    return keys


def get_endpoint_doc(agency_id: str, endpoint_id: str) -> EndpointDoc:
    requested_agency = get_agency(agency_id)
    if requested_agency.status != "active":
        raise KeyError(f"Agency '{requested_agency.id}' is planned but not implemented.")

    canonical_id = canonical_agency_id(agency_id)
    canonical_agency = get_agency(canonical_id)
    try:
        endpoint = canonical_agency.endpoints[endpoint_id]
    except KeyError as exc:
        raise KeyError(f"Unknown endpoint_id '{endpoint_id}' for agency '{agency_id}'.") from exc
    doc = _endpoint_doc_for(canonical_agency, endpoint)
    if doc is None:
        raise KeyError(f"Unknown endpoint_id '{endpoint_id}' for agency '{agency_id}'.")
    return doc


def endpoint_doc_payload(agency_id: str, endpoint_id: str) -> dict[str, Any]:
    requested_agency = get_agency(agency_id)
    if requested_agency.status != "active":
        raise KeyError(f"Agency '{requested_agency.id}' is planned but not implemented.")

    canonical_id = canonical_agency_id(agency_id)
    canonical_agency = get_agency(canonical_id)
    try:
        endpoint = canonical_agency.endpoints[endpoint_id]
    except KeyError as exc:
        raise KeyError(f"Unknown endpoint_id '{endpoint_id}' for agency '{agency_id}'.") from exc

    doc = get_endpoint_doc(agency_id, endpoint_id)
    payload = doc.to_dict()
    payload.update(
        {
            "agency": _agency_identity(requested_agency),
            "canonical_agency": _agency_identity(canonical_agency),
            "endpoint": {
                "id": endpoint.id,
                "method": endpoint.method,
                "path": endpoint.path,
                "description": endpoint.description,
                "docs_url": endpoint.docs_url,
                "default_query": endpoint.default_query,
                "status": endpoint.status,
                "status_note": endpoint.status_note,
                "alternatives": list(endpoint.alternatives),
                "redirect_policy": endpoint.redirect_policy,
            },
            "auth": {
                "kind": endpoint.auth,
                "location": endpoint.auth_location,
                "name": endpoint.auth_name,
                "env": list(AUTH_ENV[endpoint.auth]),
                "demo_key_supported": endpoint.demo_key is not None,
                "demo_key_enabled_by": "GOVDATA_ALLOW_DEMO_KEY" if endpoint.demo_key else None,
            },
        }
    )
    if requested_agency.id != canonical_agency.id:
        payload["alias"] = {
            "agency_id": requested_agency.id,
            "canonical_agency_id": canonical_agency.id,
            "note": "Endpoint documentation is maintained on the canonical agency entry.",
        }
    return payload


def endpoint_parameters_payload(agency_id: str, endpoint_id: str) -> dict[str, Any]:
    payload = endpoint_doc_payload(agency_id, endpoint_id)
    return {
        "agency": payload["agency"],
        "canonical_agency": payload["canonical_agency"],
        "endpoint": payload["endpoint"],
        "auth": payload["auth"],
        "schema": payload["schema"],
    }


def endpoint_examples_payload(agency_id: str, endpoint_id: str) -> dict[str, Any]:
    payload = endpoint_doc_payload(agency_id, endpoint_id)
    return {
        "agency": payload["agency"],
        "canonical_agency": payload["canonical_agency"],
        "endpoint": payload["endpoint"],
        "examples": payload["examples"],
    }


def agency_documentation_summary(agency_id: str) -> dict[str, Any]:
    requested_agency = get_agency(agency_id)
    canonical_id = canonical_agency_id(agency_id)
    source_agency = get_agency(canonical_id)
    endpoint_agency = source_agency if requested_agency.status == "active" else requested_agency

    summary = _agency_identity(requested_agency)
    summary.update(
        {
            "status": requested_agency.status,
            "category": requested_agency.category,
            "description": requested_agency.description,
            "rate_limit_note": requested_agency.rate_limit_note,
            "passthrough_prefixes": list(requested_agency.passthrough_prefixes),
            "passthrough_methods": list(requested_agency.passthrough_methods),
            "default_auth": requested_agency.default_auth,
            "endpoints": [],
        }
    )
    if requested_agency.id != canonical_id:
        summary["canonical_agency_id"] = canonical_id
        summary["alias_note"] = "Endpoint docs and examples are maintained on the canonical agency entry."

    endpoints: list[dict[str, Any]] = []
    for endpoint in endpoint_agency.endpoints.values():
        doc = _endpoint_doc_for(source_agency, endpoint)
        endpoint_summary: dict[str, Any] = {
            "id": endpoint.id,
            "method": endpoint.method,
            "path": endpoint.path,
            "description": endpoint.description,
            "docs_url": endpoint.docs_url,
            "auth": endpoint.auth,
            "status": endpoint.status,
            "status_note": endpoint.status_note,
            "alternatives": list(endpoint.alternatives),
            "redirect_policy": endpoint.redirect_policy,
            "has_parameter_schema": doc is not None,
            "example_count": len(doc.examples) if doc else 0,
        }
        if requested_agency.id != canonical_id:
            endpoint_summary["canonical_agency_id"] = canonical_id
            endpoint_summary["canonical_endpoint_id"] = endpoint.id
        endpoints.append(endpoint_summary)
    summary["endpoints"] = endpoints
    return summary


def _agency_identity(agency: Agency) -> dict[str, Any]:
    return {
        "id": agency.id,
        "name": agency.name,
        "base_url": agency.base_url,
        "docs_url": agency.docs_url,
    }


def _endpoint_doc_for(agency: Agency, endpoint: Endpoint) -> EndpointDoc | None:
    doc = ENDPOINT_DOCS.get((agency.id, endpoint.id))
    if doc is not None:
        return doc
    if endpoint.status == "active":
        return None
    examples = _examples_for(agency, endpoint)
    return EndpointDoc(
        schema=_schema_for(agency, endpoint),
        examples=examples,
        common_gotchas=_gotchas_for(agency, endpoint),
        official_docs_urls=_docs_urls_for(agency, endpoint),
    )


def _spec(
    name: str,
    location: ParameterLocation,
    value_type: str,
    description: str,
    *,
    required: bool = False,
    default: Any | None = None,
    enum: tuple[str, ...] = (),
    minimum: int | float | None = None,
    maximum: int | float | None = None,
    pattern: str | None = None,
    repeatable: bool = False,
    docs_url: str | None = None,
) -> ParameterSpec:
    return ParameterSpec(
        name=name,
        location=location,
        type=value_type,
        required=required,
        default=default,
        enum=enum,
        minimum=minimum,
        maximum=maximum,
        pattern=pattern,
        repeatable=repeatable,
        description=description,
        docs_url=docs_url,
    )


def _q(
    name: str,
    value_type: str,
    description: str,
    *,
    required: bool = False,
    default: Any | None = None,
    enum: tuple[str, ...] = (),
    minimum: int | float | None = None,
    maximum: int | float | None = None,
    pattern: str | None = None,
    repeatable: bool = False,
    docs_url: str | None = None,
) -> ParameterSpec:
    return _spec(
        name,
        "query",
        value_type,
        description,
        required=required,
        default=default,
        enum=enum,
        minimum=minimum,
        maximum=maximum,
        pattern=pattern,
        repeatable=repeatable,
        docs_url=docs_url,
    )


def _b(
    name: str,
    value_type: str,
    description: str,
    *,
    required: bool = False,
    default: Any | None = None,
    enum: tuple[str, ...] = (),
    minimum: int | float | None = None,
    maximum: int | float | None = None,
    pattern: str | None = None,
    repeatable: bool = False,
    docs_url: str | None = None,
) -> ParameterSpec:
    return _spec(
        name,
        "body",
        value_type,
        description,
        required=required,
        default=default,
        enum=enum,
        minimum=minimum,
        maximum=maximum,
        pattern=pattern,
        repeatable=repeatable,
        docs_url=docs_url,
    )


def _schema(
    endpoint: Endpoint,
    *,
    query: tuple[ParameterSpec, ...] = (),
    body: tuple[ParameterSpec, ...] = (),
    dynamic_fields: tuple[str, ...] = (),
    notes: tuple[str, ...] = (),
) -> EndpointSchema:
    return EndpointSchema(
        path_parameters=_path_parameter_specs(endpoint),
        query_parameters=query,
        body_parameters=body,
        dynamic_fields=dynamic_fields,
        notes=notes,
    )


def _path_parameter_specs(endpoint: Endpoint) -> tuple[ParameterSpec, ...]:
    return tuple(
        _spec(
            name,
            "path",
            _PATH_PARAM_TYPES.get(name, "string"),
            _PATH_PARAM_DESCRIPTIONS.get(name, f"Value for path placeholder {{{name}}}."),
            required=True,
            pattern=_PATH_PARAM_PATTERNS.get(name),
        )
        for name in PATH_VAR_RE.findall(endpoint.path)
    )


_PATH_PARAM_TYPES: dict[str, str] = {
    "bill_number": "integer",
    "category": "string",
    "collection": "string",
    "congress": "integer",
    "dataset": "string",
    "fdc_id": "integer",
    "id": "string",
    "dataset_name": "string",
    "data_table_name": "string",
    "download_path": "string",
    "extract_number": "integer",
    "offense": "string",
    "ori": "string",
    "package_id": "string",
    "registration_number": "string",
    "resource": "string",
    "route": "string",
    "series_id": "string",
    "start_date": "date",
    "state_abbr": "string",
    "term": "string",
    "year": "integer",
}

_PATH_PARAM_PATTERNS: dict[str, str] = {
    "bill_type": "^[a-z]+$",
    "collection": "^[A-Z0-9]+$",
    "dataset": "^[A-Za-z0-9_/-]+$",
    "dataset_name": "^[A-Za-z0-9_.-]+$",
    "download_path": "^[A-Za-z0-9_./-]+$",
    "offense": "^[a-z0-9-]+$",
    "ori": "^[A-Z0-9]{7,9}$",
    "registration_number": "^[0-9]+$",
    "route": "^[A-Za-z0-9_/-]+$",
    "supplemental_path": "^[A-Za-z0-9_./-]+$",
    "state_abbr": "^[A-Z]{2}$",
}

_PATH_PARAM_DESCRIPTIONS: dict[str, str] = {
    "bill_number": "Bill number without the bill-type prefix.",
    "bill_type": "Congress.gov bill type such as hr, s, hjres, or sconres.",
    "category": "USAspending spending_by_category path segment such as awarding_agency, cfda, naics, recipient, or state_territory.",
    "collection": "govinfo collection code such as BILLS, FR, or CREC.",
    "congress": "Numbered Congress.",
    "dataset": "Census dataset path segment, for example acs/acs5.",
    "dataset_name": "IPUMS NHGIS or IHGIS dataset identifier.",
    "download_path": "Path component from an IPUMS downloadLinks URL after https://api.ipums.org/downloads/.",
    "extract_number": "IPUMS extract number returned when an extract request is submitted.",
    "fdc_id": "FoodData Central food identifier.",
    "id": "Provider record identifier.",
    "offense": "FBI CDE offense slug such as violent-crime, property-crime, homicide, robbery, burglary, larceny, or arson.",
    "ori": "FBI Originating Agency Identifier returned by the CDE agencies endpoint.",
    "package_id": "govinfo package identifier.",
    "registration_number": "FARA registration number.",
    "resource": "Commerce API resource name such as news, blogs, or image.",
    "route": "EIA API v2 route without the leading slash.",
    "series_id": "Legacy EIA series identifier.",
    "start_date": "Collection start date in YYYY-MM-DD format.",
    "state_abbr": "Two-letter state abbreviation.",
    "supplemental_path": "Path component after https://api.ipums.org/supplemental-data/.",
    "year": "Four-digit dataset year.",
}

_PATH_SAMPLES: dict[str, Any] = {
    "bill_number": 2,
    "bill_type": "hr",
    "category": "awarding_agency",
    "collection": "CREC",
    "congress": 118,
    "dataset": "acs/acs5",
    "dataset_name": "2017_2021_ACS5a",
    "download_path": "cps/api/v1/extracts/590142/cps_00001.dat.gz",
    "extract_number": 1,
    "fdc_id": 2012128,
    "id": "123456",
    "offense": "violent-crime",
    "ori": "CA0010000",
    "package_id": "CREC-2018-10-10",
    "registration_number": "2165",
    "resource": "news",
    "route": "electricity/rto/region-data",
    "series_id": "ELEC.GEN.ALL-US-99.A",
    "start_date": "2018-10-01T00:00:00Z",
    "state_abbr": "CA",
    "supplemental_path": "nhgis/crosswalks/nhgis_blk2010_blk2020_25.zip",
    "year": 2023,
}


def _sample_path_params(endpoint: Endpoint, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    path_params = {name: _PATH_SAMPLES[name] for name in PATH_VAR_RE.findall(endpoint.path)}
    if overrides:
        path_params.update(overrides)
    return path_params


def _example(
    endpoint: Endpoint,
    title: str,
    purpose: str,
    *,
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    expected: str,
    variant: str,
) -> EndpointExample:
    return EndpointExample(
        title=title,
        purpose=purpose,
        path_params=_sample_path_params(endpoint, path_params),
        query=query or {},
        body=body or {},
        expected_response_notes=expected,
        data_source_variant=variant,
    )


def _limit(name: str = "limit", default: int | None = None, maximum: int | None = None) -> ParameterSpec:
    return _q(
        name,
        "integer",
        "Maximum records to return.",
        default=default,
        minimum=1,
        maximum=maximum,
    )


def _offset(name: str = "offset") -> ParameterSpec:
    return _q(name, "integer", "Zero-based result offset for pagination.", default=0, minimum=0)


def _format(default: str = "json", enum: tuple[str, ...] = ("json",)) -> ParameterSpec:
    return _q("format", "string", "Response format.", default=default, enum=enum)


def _fields(location: ParameterLocation = "query") -> ParameterSpec:
    return _spec(
        "fields",
        location,
        "string",
        "Comma-separated response fields to keep the payload compact.",
    )


def _schema_for(agency: Agency, endpoint: Endpoint) -> EndpointSchema:
    aid = agency.id
    eid = endpoint.id

    if aid == "datagov":
        if eid == "search":
            return _schema(
                endpoint,
                query=(
                    _q("q", "string", "Free-text search terms."),
                    _q("org_slug", "string", "Catalog organization slug."),
                    _q("org_type", "string", "Organization type filter."),
                    _q("keyword", "array[string]", "Catalog keyword filters.", repeatable=True),
                    _q("per_page", "integer", "Results per page.", default=10, minimum=1, maximum=100),
                    _q("after", "string", "Cursor or page token returned by a previous response."),
                ),
                notes=("Use catalog search before direct endpoint calls when a user gives a topic, not a source.",),
            )
        return _schema(
            endpoint,
            query=(
                _q("q", "string", "Optional text filter."),
                _q("page", "integer", "Page number where supported.", minimum=1),
                _q("per_page", "integer", "Results per page where supported.", minimum=1, maximum=100),
            ),
        )

    if aid == "agriculture":
        if eid == "food":
            return _schema(
                endpoint,
                query=(
                    _q("format", "string", "Food detail shape.", enum=("abridged", "full")),
                    _q("nutrients", "array[integer]", "Nutrient numbers to include.", repeatable=True),
                ),
            )
        if eid == "foods":
            return _schema(
                endpoint,
                body=(
                    _b("fdcIds", "array[integer]", "FDC IDs to retrieve.", required=True),
                    _b("format", "string", "Food detail shape.", enum=("abridged", "full")),
                    _b("nutrients", "array[integer]", "Nutrient numbers to include."),
                ),
            )
        if eid == "foods_list":
            return _schema(
                endpoint,
                query=(
                    _q("dataType", "array[string]", "Food data types to include.", repeatable=True),
                    _q("pageSize", "integer", "Page size.", default=50, minimum=1, maximum=200),
                    _q("pageNumber", "integer", "One-based page number.", default=1, minimum=1),
                    _q("sortBy", "string", "Sort field."),
                    _q("sortOrder", "string", "Sort direction.", enum=("asc", "desc")),
                ),
            )
        return _schema(
            endpoint,
            body=(
                _b("query", "string", "Food search terms.", required=True),
                _b("dataType", "array[string]", "Food data types to include."),
                _b("brandOwner", "string", "Brand owner filter for branded foods."),
                _b("pageSize", "integer", "Page size.", default=50, minimum=1, maximum=200),
                _b("pageNumber", "integer", "One-based page number.", default=1, minimum=1),
                _b("sortBy", "string", "Sort field."),
                _b("sortOrder", "string", "Sort direction.", enum=("asc", "desc")),
            ),
            dynamic_fields=("Food data types and nutrient IDs are discoverable from FoodData Central metadata.",),
        )

    if aid == "census":
        path_notes = ("The dataset path is dynamic; inspect dataset, variables, and geography metadata first.",)
        if eid == "data":
            return _schema(
                endpoint,
                query=(
                    _q("get", "string", "Comma-separated variable names to return.", required=True),
                    _q("for", "string", "Target geography predicate such as state:* or county:*.", required=True),
                    _q("in", "string", "Parent geography predicate such as state:06."),
                    _q("ucgid", "string", "Unified Census geography identifier."),
                ),
                dynamic_fields=("Variables and geography predicates vary by dataset and year.",),
                notes=path_notes,
            )
        return _schema(endpoint, dynamic_fields=("Metadata shape varies by Census dataset.",), notes=path_notes)

    if aid == "bls":
        if eid == "timeseries":
            return _schema(
                endpoint,
                body=(
                    _b("seriesid", "array[string]", "BLS series IDs.", required=True),
                    _b("startyear", "string", "Start year, required unless using latest."),
                    _b("endyear", "string", "End year, required unless using latest."),
                    _b("latest", "boolean", "Return latest observations only."),
                    _b("catalog", "boolean", "Include catalog metadata."),
                    _b("calculations", "boolean", "Include net and percent changes."),
                    _b("annualaverage", "boolean", "Include annual averages."),
                    _b("aspects", "boolean", "Include additional series aspects."),
                ),
                notes=("The MCP injects registrationkey into the JSON body when BLS_API_KEY is set.",),
            )
        return _schema(endpoint)

    if aid == "usaspending":
        if eid.startswith("search_"):
            return _schema(
                endpoint,
                body=(
                    _b("filters", "object", "USAspending filters such as time_period, agencies, award_type_codes, or place_of_performance_locations."),
                    _b("fields", "array[string]", "Award fields to return where supported."),
                    _b("subawards", "boolean", "Include subawards where supported.", default=False),
                    _b("page", "integer", "One-based page number.", default=1, minimum=1),
                    _b("limit", "integer", "Page size.", default=10, minimum=1, maximum=100),
                    _b("sort", "string", "Sort field."),
                    _b("order", "string", "Sort direction.", enum=("asc", "desc")),
                ),
                dynamic_fields=("Valid filters, fields, and category path segments vary by USAspending endpoint.",),
            )
        return _schema(endpoint)

    if aid == "commerce":
        return _schema(
            endpoint,
            query=(
                _q("page[limit]", "integer", "Page size.", default=10, minimum=1, maximum=50),
                _q("page[offset]", "integer", "Result offset.", default=0, minimum=0),
                _q("sort", "string", "Sort field."),
                _q("q", "string", "Keyword search. Use this for Commerce image searches."),
                _q("filter[created]", "string", "Created-date filter where supported."),
            ),
        )

    if aid == "education":
        return _schema(
            endpoint,
            query=(
                _q("fields", "string", "Comma-separated Scorecard fields to return."),
                _q("per_page", "integer", "Results per page.", default=20, minimum=1, maximum=100),
                _q("page", "integer", "Zero-based page number.", default=0, minimum=0),
                _q("sort", "string", "Sort expression such as latest.student.size:desc."),
                _q("school.state", "string", "Two-letter institution state."),
                _q("school.name", "string", "Institution name search."),
                _q("school.degrees_awarded.predominant", "integer", "Predominant degree code such as 3 for bachelor's schools."),
                _q("id", "integer", "OPEID6 or unit ID lookup where supported."),
                _q("all_programs_nested", "boolean", "Return all nested field-of-study objects instead of only matched programs."),
            ),
            dynamic_fields=("Scorecard fields are numerous; use the official data dictionary for obscure field names.",),
        )

    if aid == "justice":
        if eid.startswith("summarized_"):
            return _schema(
                endpoint,
                query=(
                    _q("from", "string", "Inclusive start month in MM-YYYY format.", required=True, pattern=r"^\d{2}-\d{4}$"),
                    _q("to", "string", "Inclusive end month in MM-YYYY format.", required=True, pattern=r"^\d{2}-\d{4}$"),
                    _q("output", "string", "Response format.", default="json", enum=("json", "csv")),
                ),
                notes=("Use MM-YYYY dates such as 01-2020 and 12-2020 for summarized CDE routes.",),
            )
        return _schema(
            endpoint,
            query=(
                _fields(),
                _q("page", "integer", "One-based page number.", default=1, minimum=1),
                _q("per_page", "integer", "Results per page.", default=20, minimum=1, maximum=1000),
                _q("output", "string", "Response format.", default="json", enum=("json", "csv")),
            ),
        )

    if aid == "justice_ncvs":
        return _schema(
            endpoint,
            query=(
                _q("$limit", "integer", "Maximum rows to return.", default=5, minimum=1, maximum=50000),
                _q("$offset", "integer", "Result offset.", default=0, minimum=0),
                _q("$select", "string", "Socrata-style field projection."),
                _q("$where", "string", "Socrata-style filter expression."),
                _q("$order", "string", "Socrata-style order expression."),
                _q("year", "integer", "Survey year."),
                _q("sex", "string", "Victim/person sex code where present."),
                _q("race", "string", "Race code where present."),
                _q("race_ethnicity", "string", "Race/ethnicity code where present."),
                _q("ager", "string", "Age-range code for personal datasets."),
                _q("hhage", "string", "Householder age code for household datasets."),
            ),
            dynamic_fields=("NCVS select datasets expose Socrata-style fields that differ between personal and household tables.",),
            notes=("Send API_DATA_GOV_KEY as the X-Api-Key header; do not add api_key as a query parameter.",),
        )

    if aid == "justice_crimesolutions":
        program_filters = (
            _q("all", "string", "Include the complete published CSV feed; use an empty value for the all flag.", default=""),
            _q("program-search", "string", "Program keyword search.", docs_url="https://catalog.data.gov/dataset/crimesolutions-gov-programs"),
            _q("program_evidence_rating", "string", "Program evidence rating filter.", enum=("Effective", "Promising", "No Effects", "Inconclusive")),
            _q("program_type", "string", "Program type/category filter."),
        )
        practice_filters = (
            _q("all", "string", "Include the complete published CSV feed; use an empty value for the all flag.", default=""),
            _q("practice-search", "string", "Practice keyword search.", docs_url="https://catalog.data.gov/dataset/crimesolutions-gov-practices"),
            _q("practice_evidence_rating", "string", "Practice evidence rating filter.", enum=("Effective", "Promising", "No Effects", "Inconclusive")),
            _q("practice_type", "string", "Practice type/category filter."),
        )
        return _schema(
            endpoint,
            query=program_filters if eid == "programs" else practice_filters,
            notes=("CrimeSolutions data endpoints currently return CSV content; JSON format requests may be rejected upstream.",),
        )

    if aid == "justice_fara":
        if eid == "registrants_new":
            return _schema(
                endpoint,
                query=(
                    _q("from", "string", "Inclusive start date in MM-DD-YYYY format.", required=True, pattern=r"^\d{2}-\d{2}-\d{4}$"),
                    _q("to", "string", "Inclusive end date in MM-DD-YYYY format.", required=True, pattern=r"^\d{2}-\d{2}-\d{4}$"),
                ),
                notes=(
                    "FARA documents a 5 requests per 10 seconds throttle; the MCP rate gate spaces registered FARA calls by 3 seconds.",
                    "Current FARA docs say v1 endpoints do not require authorization; the MCP does not inject API_DATA_GOV_KEY for FARA.",
                ),
            )
        return _schema(
            endpoint,
                notes=(
                    "FARA documents a 5 requests per 10 seconds throttle; the MCP rate gate spaces registered FARA calls by 3 seconds.",
                    "FARA responses may be encoded as ISO-8859-1/ANSI by the upstream service.",
                    "Current FARA docs say v1 endpoints do not require authorization; the MCP does not inject API_DATA_GOV_KEY for FARA.",
                ),
            )

    if aid == "treasury":
        return _schema(
            endpoint,
            query=(
                _q("fields", "string", "Comma-separated fields."),
                _q("filter", "string", "Fiscal Data filter expression."),
                _q("sort", "string", "Comma-separated sort fields, prefix descending fields with -."),
                _q("page[size]", "integer", "Page size.", default=100, minimum=1, maximum=10000),
                _q("page[number]", "integer", "One-based page number.", default=1, minimum=1),
                _format(enum=("json", "csv", "xml")),
            ),
        )

    if aid == "eia":
        if eid == "metadata":
            return _schema(endpoint, notes=("Route facets and frequencies are discoverable from metadata responses.",))
        if eid == "seriesid":
            return _schema(endpoint)
        return _schema(
            endpoint,
            query=(
                _q("frequency", "string", "Route frequency such as hourly, daily, monthly, quarterly, or annual."),
                _q("data[]", "array[string]", "Data columns to return.", repeatable=True),
                _q("facets[...]", "array[string]", "Route-specific facet filters.", repeatable=True),
                _q("start", "string", "Start period in the route frequency format."),
                _q("end", "string", "End period in the route frequency format."),
                _q("sort[0][column]", "string", "Sort column."),
                _q("sort[0][direction]", "string", "Sort direction.", enum=("asc", "desc")),
                _offset(),
                _q("length", "integer", "Maximum rows to return.", default=5000, minimum=1, maximum=5000),
            ),
            dynamic_fields=("Facet names, data columns, and frequency values are route-specific.",),
        )

    if aid == "epa":
        return _schema(
            endpoint,
            query=(
                _q("output", "string", "Response format.", default="JSON", enum=("JSON", "CSV", "XML")),
                _q("p_st", "string", "State abbreviation filter."),
                _q("p_city", "string", "City filter."),
                _q("p_zip", "string", "ZIP code filter."),
                _q("p_act", "string", "Active facility flag where supported."),
                _q("p_id", "string", "Registry or program facility identifier for detailed reports."),
                _q("responseset", "integer", "Response page number where supported.", minimum=1),
            ),
            dynamic_fields=("EPA ECHO uses program-specific p_* parameters; consult endpoint docs for narrow filters.",),
        )

    if aid == "fcc":
        return _schema(
            endpoint,
            query=(
                _q("latitude", "number", "Latitude in decimal degrees."),
                _q("longitude", "number", "Longitude in decimal degrees."),
                _q("lat", "number", "Latitude alias accepted by some FCC area calls."),
                _q("lon", "number", "Longitude alias accepted by some FCC area calls."),
                _q("censusYear", "integer", "Census vintage.", enum=("2010", "2020")),
                _format(enum=("json", "jsonp", "xml")),
            ),
        )

    if aid == "fdic":
        return _schema(
            endpoint,
            query=(
                _fields(),
                _q("filters", "string", "BankFind filter expression such as STALP:NC."),
                _q("sort_by", "string", "Sort field."),
                _q("sort_order", "string", "Sort direction.", enum=("ASC", "DESC")),
                _limit(default=10, maximum=10000),
                _offset(),
                _format(enum=("json", "csv")),
            ),
            dynamic_fields=("Fields and filter names vary across FDIC BankFind resources.",),
        )

    if aid == "fec":
        if eid == "elections":
            return _schema(
                endpoint,
                query=(
                    _q("cycle", "integer", "Two-year election cycle.", required=True),
                    _q("office", "string", "Federal office.", required=True, enum=("president", "senate", "house")),
                    _q("state", "string", "US state or territory for Senate and House elections."),
                    _q("district", "string", "Two-digit House district where applicable."),
                    _q("election_full", "boolean", "Whether to return the full election period instead of a two-year cycle."),
                    _q("per_page", "integer", "Results per page.", default=20, minimum=1, maximum=100),
                    _q("page", "integer", "One-based page number.", default=1, minimum=1),
                    _q("sort", "string", "Sort field."),
                    _q("sort_hide_null", "boolean", "Hide null values when sorting."),
                ),
            )
        return _schema(
            endpoint,
            query=(
                _q("per_page", "integer", "Results per page.", default=20, minimum=1, maximum=100),
                _q("page", "integer", "One-based page number.", default=1, minimum=1),
                _q("sort", "string", "Sort field."),
                _q("sort_hide_null", "boolean", "Hide null values when sorting."),
                _q("election_year", "integer", "Election cycle year."),
                _q("office", "string", "Federal office.", enum=("P", "S", "H")),
                _q("committee_id", "string", "FEC committee identifier."),
                _q("candidate_id", "string", "FEC candidate identifier."),
                _q("two_year_transaction_period", "integer", "Two-year transaction period."),
                _q("min_date", "date", "Inclusive minimum transaction or filing date."),
                _q("max_date", "date", "Inclusive maximum transaction or filing date."),
            ),
            dynamic_fields=("OpenFEC supports many endpoint-specific filters; this schema covers common paging and identifier filters.",),
        )

    if aid == "ftc":
        if eid == "hsr_early_termination_notices":
            return _schema(
                endpoint,
                notes=("Do not send stale Socrata paging parameters to this endpoint; the upstream route accepts a plain API-keyed request.",),
            )
        return _schema(
            endpoint,
            query=(
                _q("$limit", "integer", "Maximum rows to return.", default=1000, minimum=1, maximum=50000),
                _q("$offset", "integer", "Result offset.", default=0, minimum=0),
                _q("$order", "string", "Socrata-style order expression."),
                _q("$select", "string", "Socrata-style field projection."),
                _q("$where", "string", "Socrata-style filter expression."),
            ),
        )

    if aid == "fda":
        return _schema(
            endpoint,
            query=(
                _q("search", "string", "openFDA search expression."),
                _q("count", "string", "Field to aggregate counts by."),
                _limit(default=1, maximum=1000),
                _q("skip", "integer", "Result offset.", default=0, minimum=0, maximum=25000),
                _q("sort", "string", "Sort expression such as receivedate:desc."),
            ),
            dynamic_fields=("Search fields vary by openFDA dataset; use openFDA field docs for specialized fields.",),
        )

    if aid == "gsa":
        return _schema(endpoint, notes=("This endpoint returns the API directory page rather than a narrow JSON dataset.",))

    if aid == "govinfo":
        if eid == "search":
            return _schema(
                endpoint,
                body=(
                    _b("query", "string", "govinfo search query.", required=True),
                    _b("pageSize", "integer", "Page size.", default=10, minimum=1, maximum=100),
                    _b("offsetMark", "string", "Cursor returned by previous search response; use * for the first page.", default="*"),
                    _b("sorts", "array[object]", "Sort definitions."),
                    _b("historical", "boolean", "Include historical collections where supported."),
                ),
            )
        return _schema(
            endpoint,
            query=(
                _q("pageSize", "integer", "Page size.", default=10, minimum=1, maximum=100),
                _q("offsetMark", "string", "Cursor returned by previous response; use * for the first page.", default="*"),
                _q("offset", "integer", "Zero-based row offset where supported.", default=0, minimum=0),
                _q("granuleClass", "string", "Granule class filter where supported."),
            ),
        )

    if aid == "loc":
        if eid == "bill_detail":
            return _schema(endpoint, query=(_format(),))
        return _schema(
            endpoint,
            query=(
                _format(),
                _limit(default=20, maximum=250),
                _offset(),
                _q("fromDateTime", "datetime", "Lower bound update timestamp."),
                _q("toDateTime", "datetime", "Upper bound update timestamp."),
                _q("congress", "integer", "Numbered Congress filter where supported."),
                _q("billType", "string", "Bill type filter where supported."),
            ),
        )

    if aid == "nih_reporter":
        return _schema(
            endpoint,
            body=(
                _b("criteria", "object", "NIH RePORTER criteria object.", required=True),
                _b("include_fields", "array[string]", "Fields to include in the response."),
                _b("exclude_fields", "array[string]", "Fields to omit from the response."),
                _b("offset", "integer", "Result offset.", default=0, minimum=0),
                _b("limit", "integer", "Page size.", default=50, minimum=1, maximum=500),
                _b("sort_field", "string", "Sort field."),
                _b("sort_order", "string", "Sort direction.", enum=("asc", "desc")),
            ),
            dynamic_fields=("Criteria and include_fields are extensive; use RePORTER docs for the full field catalog.",),
            notes=("Keep limit <= 500; the MCP rate gate spaces registered NIH RePORTER calls by 3 seconds.",),
        )

    if aid == "nrel":
        if eid == "pvwatts_v8":
            return _schema(
                endpoint,
                query=(
                    _q("lat", "number", "Latitude.", required=True),
                    _q("lon", "number", "Longitude.", required=True),
                    _q("system_capacity", "number", "System size in kW.", required=True),
                    _q("module_type", "integer", "Module type code.", required=True, enum=("0", "1", "2")),
                    _q("losses", "number", "System losses percentage.", required=True),
                    _q("array_type", "integer", "Array type code.", required=True),
                    _q("tilt", "number", "Array tilt in degrees.", required=True),
                    _q("azimuth", "number", "Array azimuth in degrees.", required=True),
                    _q("timeframe", "string", "Monthly or hourly output.", enum=("monthly", "hourly")),
                ),
            )
        return _schema(
            endpoint,
            query=(
                _q("fuel_type", "string", "Alternative fuel type code."),
                _q("state", "string", "State abbreviation."),
                _q("zip", "string", "ZIP code."),
                _q("latitude", "number", "Latitude for nearest searches."),
                _q("longitude", "number", "Longitude for nearest searches."),
                _q("radius", "number", "Search radius in miles."),
                _limit(default=20),
                _format(enum=("json",)),
            ),
        )

    if aid == "fred":
        common = (
            _q("file_type", "string", "Response format; the MCP defaults this to json.", default="json", enum=("json",)),
            _limit(default=1000),
            _offset(),
        )
        if eid == "series_search":
            return _schema(
                endpoint,
                query=(
                    _q("search_text", "string", "Series search text.", required=True),
                    _q("tag_names", "string", "Semicolon-separated tags."),
                    _q("filter_variable", "string", "Filter variable such as frequency or units."),
                    _q("sort_order", "string", "Sort direction.", enum=("asc", "desc")),
                    *common,
                ),
            )
        if eid in {"series", "series_observations"}:
            extra = (_q("series_id", "string", "FRED series ID.", required=True),)
            if eid == "series_observations":
                extra += (
                    _q("observation_start", "date", "Observation start date."),
                    _q("observation_end", "date", "Observation end date."),
                    _q("units", "string", "Units transformation."),
                    _q("frequency", "string", "Frequency aggregation."),
                    _q("aggregation_method", "string", "Aggregation method."),
                )
            return _schema(endpoint, query=extra + common)
        if eid in {"category", "category_children"}:
            return _schema(endpoint, query=(_q("category_id", "integer", "FRED category ID.", required=eid == "category"), *common))
        if eid in {"release", "release_series", "v2_release_observations"}:
            extra = (_q("release_id", "integer", "FRED release ID.", required=True),)
            if eid == "v2_release_observations":
                extra += (
                    _q("observation_start", "date", "Observation start date."),
                    _q("observation_end", "date", "Observation end date."),
                )
            return _schema(endpoint, query=extra + common)
        return _schema(endpoint, query=common)

    if aid == "datausa":
        if eid == "data":
            return _schema(
                endpoint,
                query=(
                    _q("cube", "string", "Tesseract cube name such as acs_yg_total_population_5.", required=True),
                    _q("measures", "string", "Comma-separated measures such as Population.", required=True),
                    _q("drilldowns", "string", "Comma-separated dimensions such as State,Year."),
                    _q("include", "string", "Dimension member filter such as Year:2023 or State:04000US06."),
                    _q("limit", "string", "Limit and offset pair such as 100,0."),
                    _q("sort", "string", "Sort expression such as Population.asc."),
                ),
                dynamic_fields=("Cubes, dimensions, levels, and measures are discoverable through the Data USA Tesseract cube list and cube schema endpoints.",),
            )
        return _schema(
            endpoint,
            query=(
                _q("locale", "string", "Optional locale accepted by the Tesseract cubes endpoint."),
            ),
            notes=("The legacy /api/search endpoint returned 404 in manual testing; this endpoint now lists Tesseract cubes for dataset discovery.",),
        )

    if aid == "ipums":
        collection = _q(
            "collection",
            "string",
            "IPUMS collection identifier.",
            required=True,
            enum=("usa", "cps", "international", "dhs", "atus", "ahtus", "mtus", "meps", "nhis", "nhgis", "ihgis"),
        )
        version = _q("version", "integer", "IPUMS API version.", default=2, minimum=2)
        if eid in {"extracts", "extract"}:
            return _schema(
                endpoint,
                query=(collection, version, _limit(default=10)),
                notes=("Extracts are asynchronous; completed responses include downloadLinks.",),
            )
        if eid == "create_extract":
            return _schema(
                endpoint,
                query=(collection, version),
                body=(
                    _b("description", "string", "Short extract description."),
                    _b("dataStructure", "object", "Microdata extract structure such as rectangular or hierarchical."),
                    _b("dataFormat", "string", "Requested data format.", enum=("fixed_width", "csv", "csv_header", "csv_no_header")),
                    _b("samples", "object", "Microdata sample selections keyed by sample ID."),
                    _b("variables", "object", "Microdata variable selections keyed by variable mnemonic."),
                    _b("datasets", "object", "NHGIS/IHGIS dataset selections keyed by dataset name."),
                    _b("timeSeriesTables", "object", "NHGIS/IHGIS time series table selections."),
                    _b("shapefiles", "array[string]", "NHGIS/IHGIS shapefile selections."),
                ),
                dynamic_fields=("collection-specific extract payload",),
                notes=(
                    "Use microdata payload fields for usa/cps/international/dhs/atus/ahtus/mtus/meps/nhis.",
                    "Use aggregate/spatial payload fields for nhgis/ihgis.",
                    "For analysis workflows, prefer dataFormat='csv' unless fixed-width is specifically needed.",
                ),
            )
        if eid.startswith("metadata_"):
            return _schema(
                endpoint,
                query=(
                    _q("collection", "string", "Metadata collection identifier.", required=True, enum=("nhgis", "ihgis")),
                    version,
                    _q("pageNumber", "integer", "One-based page number where supported.", minimum=1),
                    _q("pageSize", "integer", "Page size where supported.", minimum=1),
                    _q("q", "string", "Keyword search where supported."),
                ),
                notes=("IPUMS microdata metadata is not generally available through the API; NHGIS/IHGIS metadata is supported.",),
            )
        if eid == "download":
            return _schema(
                endpoint,
                notes=("Use govdata_get_dataset(action='download_extract') with an extract number to poll until ready and save selected files; use govdata_get_dataset(action='download_file') only for a specific downloadLinks path.",),
            )
        if eid == "supplemental_data":
            return _schema(
                endpoint,
                notes=("Use API URLs derived from secure-assets.ipums.org supplemental data links.",),
            )

    return _schema(endpoint)


def _examples_for(agency: Agency, endpoint: Endpoint) -> tuple[EndpointExample, EndpointExample, EndpointExample]:
    aid = agency.id
    eid = endpoint.id

    if aid == "datagov":
        if eid == "search":
            return (
                _example(endpoint, "Labor catalog search", "Find a small page of labor datasets.", query={"q": "labor market", "per_page": 3}, expected="Catalog result page with dataset metadata and links.", variant="catalog-search"),
                _example(endpoint, "Census organization datasets", "Narrow catalog results to one publisher.", query={"q": "population", "org_slug": "census-gov", "per_page": 3}, expected="Dataset records associated with the Census organization slug if present.", variant="publisher-filter"),
                _example(endpoint, "Keyword-filtered search", "Use a keyword list for topical discovery.", query={"q": "poverty", "keyword": ["poverty"], "per_page": 3}, expected="Small result page with matching catalog packages.", variant="keyword-filter"),
            )
        if eid == "organizations":
            return (
                _example(endpoint, "List catalog organizations", "Inspect publishing organizations.", query={"per_page": 5}, expected="Organization records with slugs and display names.", variant="organization-list"),
                _example(endpoint, "Search organization names", "Find publishers matching a text query.", query={"q": "transportation", "per_page": 5}, expected="Matching organization records when supported by the catalog API.", variant="organization-search"),
                _example(endpoint, "Second organization page", "Page through organization results.", query={"page": 2, "per_page": 5}, expected="The second page of organization records.", variant="pagination"),
            )
        return (
            _example(endpoint, "List catalog keywords", "Inspect common keywords.", query={"per_page": 10}, expected="Keyword records or tag strings.", variant="keyword-list"),
            _example(endpoint, "Search keywords", "Find topical keywords.", query={"q": "water", "per_page": 10}, expected="Keywords matching water where supported.", variant="keyword-search"),
            _example(endpoint, "Small keyword page", "Keep keyword discovery compact.", query={"page": 1, "per_page": 5}, expected="A compact keyword page.", variant="pagination"),
        )

    if aid == "agriculture":
        if eid == "food":
            return (
                _example(endpoint, "Abridged food details", "Fetch one food with a compact response.", query={"format": "abridged"}, expected="Food description, data type, and abridged nutrient values.", variant="food-detail"),
                _example(endpoint, "Selected nutrients", "Fetch one food with selected nutrient numbers.", query={"format": "full", "nutrients": [203, 204, 205]}, expected="Full food details including requested protein, fat, and carbohydrate nutrients when present.", variant="nutrient-subset"),
                _example(endpoint, "Foundation food lookup", "Use a known FDC ID for direct lookup.", query={"format": "abridged", "nutrients": [208]}, expected="A single food record with energy where present.", variant="identifier-lookup"),
            )
        if eid == "foods":
            return (
                _example(endpoint, "Multiple abridged foods", "Fetch two foods by FDC ID.", body={"fdcIds": [2012128, 2117388], "format": "abridged"}, expected="A list of food records in requested order where IDs exist.", variant="batch-detail"),
                _example(endpoint, "Multiple foods with nutrients", "Return selected nutrient values for multiple foods.", body={"fdcIds": [2012128, 2117388], "format": "full", "nutrients": [203, 204, 205]}, expected="Food records with selected nutrient information.", variant="batch-nutrients"),
                _example(endpoint, "Single-item batch", "Use batch endpoint for one known food ID.", body={"fdcIds": [2012128], "format": "abridged"}, expected="A one-item food record list.", variant="batch-single"),
            )
        if eid == "foods_list":
            return (
                _example(endpoint, "Foundation foods page", "List a small page of foundation foods.", query={"dataType": ["Foundation"], "pageSize": 5, "pageNumber": 1}, expected="Paged food summaries.", variant="foundation-list"),
                _example(endpoint, "Branded foods page", "List a small page of branded foods.", query={"dataType": ["Branded"], "pageSize": 5, "pageNumber": 1}, expected="Paged branded food summaries.", variant="branded-list"),
                _example(endpoint, "Sorted food list", "Sort food summaries by description.", query={"pageSize": 5, "sortBy": "description", "sortOrder": "asc"}, expected="Food summaries sorted by description when supported.", variant="sorted-list"),
            )
        return (
            _example(endpoint, "Cheddar search", "Search foods by a common term.", body={"query": "cheddar cheese", "pageSize": 5}, expected="Food search results with descriptions and FDC IDs.", variant="keyword-search"),
            _example(endpoint, "Foundation lentils", "Constrain search to foundation foods.", body={"query": "lentils", "dataType": ["Foundation"], "pageSize": 5}, expected="Foundation food matches for lentils.", variant="data-type-filter"),
            _example(endpoint, "Branded cereal", "Search branded foods with a compact page.", body={"query": "oat cereal", "dataType": ["Branded"], "pageSize": 5, "sortBy": "publishedDate", "sortOrder": "desc"}, expected="Recent branded food matches where available.", variant="branded-search"),
        )

    if aid == "census":
        if eid == "dataset":
            return (
                _example(endpoint, "ACS dataset metadata", "Inspect dataset-level metadata.", expected="Dataset title, description, vintages, and links.", variant="dataset-metadata"),
                _example(endpoint, "Decennial dataset metadata", "Inspect a decennial dataset.", path_params={"year": 2020, "dataset": "dec/pl"}, expected="Metadata for the 2020 decennial PL dataset.", variant="decennial-metadata"),
                _example(endpoint, "Economic dataset metadata", "Inspect a non-ACS dataset path.", path_params={"year": 2022, "dataset": "acs/acs1"}, expected="Metadata for the selected Census dataset.", variant="dataset-variant"),
            )
        if eid == "variables":
            return (
                _example(endpoint, "ACS variables", "Fetch variable metadata before data calls.", expected="Variable names, labels, concepts, and predicates.", variant="variables-metadata"),
                _example(endpoint, "ACS profile variables", "Inspect a profile dataset's variables.", path_params={"dataset": "acs/acs5/profile"}, expected="Profile variable metadata.", variant="profile-variables"),
                _example(endpoint, "Decennial variables", "Inspect decennial variable metadata.", path_params={"year": 2020, "dataset": "dec/pl"}, expected="Variable metadata for the decennial PL dataset.", variant="decennial-variables"),
            )
        if eid == "geography":
            return (
                _example(endpoint, "ACS geography predicates", "Check supported geography levels.", expected="Supported geography predicates for ACS 5-year.", variant="geography-metadata"),
                _example(endpoint, "Profile geography predicates", "Check geography support for profiles.", path_params={"dataset": "acs/acs5/profile"}, expected="Supported geography predicates for ACS profile.", variant="profile-geography"),
                _example(endpoint, "Decennial geography predicates", "Check decennial geographies.", path_params={"year": 2020, "dataset": "dec/pl"}, expected="Supported geography predicates for decennial PL.", variant="decennial-geography"),
            )
        return (
            _example(endpoint, "State population", "Fetch a small state-level ACS table.", query={"get": "NAME,B01003_001E", "for": "state:*"}, expected="Rows with NAME and total population estimates by state.", variant="state-geography"),
            _example(endpoint, "County population in California", "Use parent geography with county rows.", query={"get": "NAME,B01003_001E", "for": "county:*", "in": "state:06"}, expected="County rows for California.", variant="county-geography"),
            _example(endpoint, "Tract population in one county", "Use tract rows inside a county.", query={"get": "NAME,B01003_001E", "for": "tract:*", "in": "state:06 county:075"}, expected="Tract rows for San Francisco County, California.", variant="tract-geography"),
        )

    if aid == "bls":
        if eid == "timeseries":
            return (
                _example(endpoint, "CPI annual span", "Fetch CPI observations for a short period.", body={"seriesid": ["CUUR0000SA0"], "startyear": "2023", "endyear": "2025"}, expected="BLS series data with year, period, value, and footnotes.", variant="single-series"),
                _example(endpoint, "Latest unemployment", "Fetch latest observations only.", body={"seriesid": ["LNS14000000"], "latest": True}, expected="Latest available unemployment rate observations.", variant="latest"),
                _example(endpoint, "Multiple series with catalog", "Fetch two series with metadata.", body={"seriesid": ["CUUR0000SA0", "LNS14000000"], "startyear": "2024", "endyear": "2025", "catalog": True}, expected="Data arrays plus catalog metadata when BLS returns it.", variant="multi-series"),
            )
        return (
            _example(endpoint, "List surveys", "Discover BLS survey codes.", expected="Survey code and name list.", variant="survey-list"),
            _example(endpoint, "Survey discovery for series selection", "Use survey list before choosing a series prefix.", expected="Survey metadata useful for selecting BLS series IDs.", variant="series-discovery"),
            _example(endpoint, "Compact survey call", "Health check the public surveys endpoint.", expected="A small JSON list or BLS status envelope.", variant="metadata-health"),
        )

    if aid == "usaspending":
        if eid == "awards_last_updated":
            return (
                _example(endpoint, "Awards update timestamp", "Check when award data was last refreshed.", expected="Timestamp or date metadata for awards data.", variant="freshness"),
                _example(endpoint, "ETL health check", "Use the endpoint as a low-volume availability check.", expected="Latest update metadata.", variant="health-check"),
                _example(endpoint, "Source recency note", "Capture recency before an award search.", expected="Award update date suitable for citation.", variant="source-metadata"),
            )
        if eid == "references_toptier_agencies":
            return (
                _example(endpoint, "Top-tier agencies", "List agencies for filter discovery.", expected="Top-tier agency names and identifiers.", variant="reference-list"),
                _example(endpoint, "Agency filter setup", "Discover agency identifiers before a search.", expected="Agency reference records usable in filters.", variant="filter-discovery"),
                _example(endpoint, "Reference health check", "Make a low-volume reference request.", expected="A reference list response.", variant="health-check"),
            )
        if eid == "search_spending_by_award":
            return (
                _example(endpoint, "Recent contracts", "Search a small page of recent contract awards.", body={"filters": {"time_period": [{"start_date": "2024-10-01", "end_date": "2025-09-30"}], "award_type_codes": ["A", "B", "C", "D"]}, "fields": ["Award ID", "Recipient Name", "Award Amount"], "page": 1, "limit": 5, "sort": "Award Amount", "order": "desc"}, expected="Award rows with selected fields and pagination metadata.", variant="award-search"),
                _example(endpoint, "Agency award search", "Search awards for one top-tier agency.", body={"filters": {"agencies": [{"type": "awarding", "tier": "toptier", "name": "Department of Energy"}]}, "fields": ["Award ID", "Recipient Name", "Start Date"], "page": 1, "limit": 5}, expected="Awards associated with the agency filter.", variant="agency-filter"),
                _example(endpoint, "Recipient keyword search", "Search awards by recipient text.", body={"filters": {"recipient_search_text": ["university"]}, "fields": ["Award ID", "Recipient Name", "Award Amount"], "page": 1, "limit": 5}, expected="Small page of matching recipient awards.", variant="recipient-filter"),
            )
        return (
            _example(endpoint, "Spending by awarding agency", "Aggregate obligations by awarding agency.", path_params={"category": "awarding_agency"}, body={"filters": {"time_period": [{"start_date": "2024-10-01", "end_date": "2025-09-30"}]}, "limit": 5}, expected="Category totals for awarding agencies.", variant="category-aggregation"),
            _example(endpoint, "Spending by recipient", "Aggregate spending by recipient.", path_params={"category": "recipient"}, body={"filters": {"award_type_codes": ["A", "B", "C", "D"]}, "limit": 5}, expected="Top recipient categories where supported.", variant="recipient-aggregation"),
            _example(endpoint, "Spending by CFDA", "Aggregate assistance spending by program.", path_params={"category": "cfda"}, body={"filters": {"award_type_codes": ["02", "03", "04", "05"]}, "limit": 5}, expected="Program category totals.", variant="assistance-aggregation"),
        )

    if aid == "commerce":
        resource = {"news": "news", "blogs": "blog posts", "image": "image records"}[eid]
        return (
            _example(endpoint, f"Recent {resource}", f"Fetch a small page of Commerce {resource}.", query={"page[limit]": 5}, expected=f"A compact page of Commerce {resource}.", variant="recent-content"),
            _example(endpoint, f"Sorted {resource}", "Sort content by created date where supported.", query={"page[limit]": 5, "sort": "-created"}, expected="Content records sorted by recency when supported.", variant="sorted-content"),
            _example(endpoint, f"Filtered {resource}", "Apply a lightweight keyword search.", query={"page[limit]": 5, "q": "trade"}, expected="Content records matching the keyword search when supported.", variant="filtered-content"),
        )

    if aid == "education":
        if eid == "schools":
            return (
                _example(endpoint, "California institutions", "Fetch a compact institution page.", query={"school.state": "CA", "fields": "id,school.name,school.state,latest.student.size", "per_page": 5}, expected="Institution records with selected fields.", variant="institution-search"),
                _example(endpoint, "Public four-year schools", "Filter by control and predominant degree.", query={"school.ownership": 1, "school.degrees_awarded.predominant": 3, "fields": "id,school.name,latest.student.size", "per_page": 5}, expected="Public institutions with predominant bachelor's degrees.", variant="program-filter"),
                _example(endpoint, "Named institution lookup", "Search by school name.", query={"school.name": "community college", "fields": "id,school.name,school.city,school.state", "per_page": 5}, expected="Institution records matching the name text.", variant="name-search"),
            )
        return (
            _example(endpoint, "Computer science fields", "Search nested field-of-study records by CIP code prefix.", query={"latest.programs.cip_4_digit.code": "1101", "fields": "id,school.name,latest.programs.cip_4_digit.title", "all_programs_nested": True, "per_page": 5}, expected="School records with nested field-of-study data for the CIP filter.", variant="cip-filter"),
            _example(endpoint, "Fields by state", "Combine school state and field projections.", query={"school.state": "TX", "fields": "id,school.name,latest.programs.cip_4_digit.title", "all_programs_nested": True, "per_page": 5}, expected="Schools in the state with nested field-of-study program data.", variant="state-filter"),
            _example(endpoint, "Compact field page", "Keep a field-of-study request low volume.", query={"fields": "id,school.name,latest.programs.cip_4_digit.credential.title", "all_programs_nested": True, "per_page": 5}, expected="A small page of school records with nested field-of-study fields.", variant="field-list"),
        )

    if aid == "justice":
        if eid == "estimates_national":
            return (
                _example(endpoint, "National estimates page", "Fetch a compact national estimates page.", query={"page": 1, "per_page": 5, "output": "json"}, expected="National crime estimate rows with pagination metadata.", variant="national-estimates"),
                _example(endpoint, "Selected national fields", "Project selected estimate fields.", query={"fields": "year,population,violent_crime", "page": 1, "per_page": 5, "output": "json"}, expected="National estimate rows limited to selected fields.", variant="field-projection"),
                _example(endpoint, "Second national page", "Fetch another compact page.", query={"page": 2, "per_page": 5, "output": "json"}, expected="Second page of national estimates where available.", variant="pagination"),
            )
        if eid == "estimates_states":
            return (
                _example(endpoint, "California estimates", "Fetch state estimates by postal code.", query={"page": 1, "per_page": 5, "output": "json"}, expected="California crime estimate rows.", variant="state-estimates"),
                _example(endpoint, "Texas estimates", "Fetch another state by path parameter.", path_params={"state_abbr": "TX"}, query={"page": 1, "per_page": 5, "output": "json"}, expected="Texas crime estimate rows.", variant="state-variant"),
                _example(endpoint, "New York fields", "Fetch selected state estimate fields.", path_params={"state_abbr": "NY"}, query={"fields": "year,population,violent_crime", "page": 1, "per_page": 5, "output": "json"}, expected="New York estimate rows with selected fields.", variant="field-projection"),
            )
        if eid == "summarized_national":
            return (
                _example(endpoint, "National violent crime summary", "Fetch national monthly summarized CDE data.", query={"from": "01-2020", "to": "12-2020"}, expected="Monthly national offense summary rows.", variant="national-summary"),
                _example(endpoint, "National property crime summary", "Fetch another offense summary.", path_params={"offense": "property-crime"}, query={"from": "01-2020", "to": "12-2020"}, expected="Monthly national property-crime summary rows.", variant="offense-variant"),
                _example(endpoint, "National summary CSV", "Request CSV output where supported.", query={"from": "01-2020", "to": "03-2020", "output": "csv"}, expected="CSV or CSV-ready summarized national data.", variant="format-variant"),
            )
        if eid == "summarized_state":
            return (
                _example(endpoint, "California violent crime summary", "Fetch monthly state CDE summaries.", query={"from": "01-2020", "to": "12-2020"}, expected="Monthly California offense summary rows.", variant="state-summary"),
                _example(endpoint, "New York robbery summary", "Use another state and offense.", path_params={"state_abbr": "NY", "offense": "robbery"}, query={"from": "01-2020", "to": "12-2020"}, expected="Monthly New York robbery summary rows.", variant="state-offense"),
                _example(endpoint, "Texas burglary summary", "Use another state/offense pair.", path_params={"state_abbr": "TX", "offense": "burglary"}, query={"from": "01-2021", "to": "12-2021"}, expected="Monthly Texas burglary summary rows.", variant="state-variant"),
            )
        if eid == "summarized_agency":
            return (
                _example(endpoint, "Agency violent crime summary", "Fetch monthly summaries for one ORI.", query={"from": "01-2020", "to": "12-2020"}, expected="Monthly agency offense summary rows.", variant="agency-summary"),
                _example(endpoint, "Agency property crime summary", "Use another offense for the same ORI.", path_params={"offense": "property-crime"}, query={"from": "01-2020", "to": "12-2020"}, expected="Monthly agency property-crime rows.", variant="offense-variant"),
                _example(endpoint, "Agency homicide summary", "Use another ORI/offense pair.", path_params={"ori": "NY0303000", "offense": "homicide"}, query={"from": "01-2021", "to": "12-2021"}, expected="Monthly agency homicide rows where the ORI reports data.", variant="agency-variant"),
            )
        return (
            _example(endpoint, "California agencies", "Discover FBI CDE agency identifiers for one state.", query={"page": 1, "per_page": 5, "output": "json"}, expected="Agency records for use in other CDE calls.", variant="agency-list"),
            _example(endpoint, "Texas agencies", "Fetch agencies for another state.", path_params={"state_abbr": "TX"}, query={"page": 1, "per_page": 5, "output": "json"}, expected="Agency records in Texas where supported.", variant="state-filter"),
            _example(endpoint, "New York agencies", "Fetch a compact agency page for a third state.", path_params={"state_abbr": "NY"}, query={"page": 1, "per_page": 5, "output": "json"}, expected="Agency records in New York.", variant="state-variant"),
        )

    if aid == "justice_ncvs":
        if eid.startswith("personal_"):
            field_query = "idper,year,ager,sex,race_ethnicity,popsize"
            return (
                _example(endpoint, "NCVS personal rows", "Fetch a compact page from a personal NCVS select dataset.", query={"$limit": 5}, expected="Personal-level NCVS select rows.", variant="personal-page"),
                _example(endpoint, "NCVS personal fields", "Project common personal fields.", query={"$select": field_query, "$limit": 5}, expected="Projected personal records with person and demographic fields.", variant="field-projection"),
                _example(endpoint, "NCVS personal year filter", "Filter personal records by survey year.", query={"year": 2022, "$limit": 5}, expected="Personal records for the selected year where present.", variant="year-filter"),
            )
        field_query = "idhh,year,hhage,hhsex,hhrace_ethnicity,popsize"
        return (
            _example(endpoint, "NCVS household rows", "Fetch a compact page from a household NCVS select dataset.", query={"$limit": 5}, expected="Household-level NCVS select rows.", variant="household-page"),
            _example(endpoint, "NCVS household fields", "Project common household fields.", query={"$select": field_query, "$limit": 5}, expected="Projected household records with household and demographic fields.", variant="field-projection"),
            _example(endpoint, "NCVS household year filter", "Filter household records by survey year.", query={"year": 2022, "$limit": 5}, expected="Household records for the selected year where present.", variant="year-filter"),
        )

    if aid == "justice_crimesolutions":
        if eid == "programs":
            return (
                _example(endpoint, "All CrimeSolutions programs", "Download the full rated programs CSV feed.", expected="CSV rows describing rated program interventions.", variant="programs-all"),
                _example(endpoint, "Effective programs", "Filter programs by evidence rating.", query={"program_evidence_rating": "Effective"}, expected="CSV rows for programs rated Effective when the filter is supported.", variant="program-rating"),
                _example(endpoint, "Program keyword search", "Search programs by keyword.", query={"program-search": "drug"}, expected="CSV rows for matching program records.", variant="program-search"),
            )
        return (
            _example(endpoint, "All CrimeSolutions practices", "Download the full rated practices CSV feed.", expected="CSV rows describing rated practice evidence.", variant="practices-all"),
            _example(endpoint, "Effective practices", "Filter practices by evidence rating.", query={"practice_evidence_rating": "Effective"}, expected="CSV rows for practices rated Effective when the filter is supported.", variant="practice-rating"),
            _example(endpoint, "Practice keyword search", "Search practices by keyword.", query={"practice-search": "juvenile"}, expected="CSV rows for matching practice records.", variant="practice-search"),
        )

    if aid == "justice_fara":
        if eid == "registrants_new":
            return (
                _example(endpoint, "New FARA registrants", "List new registrants in a short date window.", query={"from": "01-01-2024", "to": "01-31-2024"}, expected="Registrant records filed during the date range.", variant="new-registrants"),
                _example(endpoint, "New FARA registrants in February", "Use another date window.", query={"from": "02-01-2024", "to": "02-29-2024"}, expected="Registrant records filed during the second date range.", variant="date-variant"),
                _example(endpoint, "Recent new registrants", "Keep a new-registrant query bounded.", query={"from": "03-01-2024", "to": "03-15-2024"}, expected="Registrant records for the bounded range.", variant="bounded-date-range"),
            )
        if eid == "registration_documents":
            return (
                _example(endpoint, "FARA registration documents", "List documents for a registration number.", expected="Registration document metadata for the registrant.", variant="documents"),
                _example(endpoint, "FARA registration documents variant", "Use another registration number.", path_params={"registration_number": "6415"}, expected="Registration document metadata where the number exists.", variant="documents-variant"),
                _example(endpoint, "FARA document lookup", "Use document lookup before fetching filing URLs.", path_params={"registration_number": "6869"}, expected="Document metadata and filing links where available.", variant="document-discovery"),
            )
        if eid.startswith("short_forms_"):
            status = "active" if eid.endswith("active") else "terminated"
            return (
                _example(endpoint, f"FARA {status} short forms", "List short-form registrants for a registration number.", expected="Short-form registrant records.", variant=f"{status}-short-forms"),
                _example(endpoint, "FARA short forms variant", "Use another registration number.", path_params={"registration_number": "6415"}, expected="Short-form records where the registration exists.", variant="short-form-variant"),
                _example(endpoint, "FARA short-form discovery", "Inspect people associated with a registrant.", path_params={"registration_number": "6869"}, expected="Short-form records associated with the selected registrant.", variant="short-form-discovery"),
            )
        if eid.startswith("foreign_principals_"):
            status = "active" if eid.endswith("active") else "terminated"
            return (
                _example(endpoint, f"FARA {status} foreign principals", "List foreign principals for a registration number.", expected="Foreign-principal records.", variant=f"{status}-foreign-principals"),
                _example(endpoint, "FARA foreign principals variant", "Use another registration number.", path_params={"registration_number": "6415"}, expected="Foreign-principal records where the registration exists.", variant="principal-variant"),
                _example(endpoint, "FARA foreign-principal discovery", "Inspect principals associated with a registrant.", path_params={"registration_number": "6869"}, expected="Foreign-principal records associated with the selected registrant.", variant="principal-discovery"),
            )
        status = "active" if eid.endswith("active") else "terminated"
        return (
            _example(endpoint, f"FARA {status} registrants", "List FARA registrants by status.", expected="Registrant records for the selected status.", variant=f"{status}-registrants"),
            _example(endpoint, f"FARA {status} registrants health check", "Use the status list as a low-volume health check.", expected="Registrant response shape and source metadata.", variant="health-check"),
            _example(endpoint, f"FARA {status} registrant discovery", "Discover registration numbers for follow-up FARA calls.", expected="Registrant records including registration numbers where present.", variant="registrant-discovery"),
        )

    if aid == "treasury":
        base_query = {"fields": "record_date,tot_pub_debt_out_amt", "page[size]": 5, "sort": "-record_date"}
        if eid == "debt_to_penny":
            return (
                _example(endpoint, "Recent debt records", "Fetch recent Debt to the Penny rows.", query=base_query, expected="Recent debt records with selected fields.", variant="recent-records"),
                _example(endpoint, "Debt records after date", "Filter by record date.", query={**base_query, "filter": "record_date:gte:2024-01-01"}, expected="Debt records on or after the filter date.", variant="date-filter"),
                _example(endpoint, "CSV-shaped debt request", "Request CSV response where supported.", query={**base_query, "format": "csv"}, expected="CSV or CSV-ready response for selected fields.", variant="format-variant"),
            )
        return (
            _example(endpoint, "Recent exchange rates", "Fetch recent exchange-rate records.", query={"fields": "record_date,country,currency,exchange_rate", "page[size]": 5, "sort": "-record_date"}, expected="Recent reporting rates of exchange.", variant="recent-records"),
            _example(endpoint, "Exchange rates by country", "Filter exchange rates for a country.", query={"fields": "record_date,country,currency,exchange_rate", "filter": "country:eq:Canada", "page[size]": 5}, expected="Canadian exchange-rate records.", variant="country-filter"),
            _example(endpoint, "Sorted exchange rates", "Sort exchange rates by country and date.", query={"fields": "record_date,country,exchange_rate", "sort": "country,-record_date", "page[size]": 5}, expected="Sorted exchange-rate rows.", variant="sort"),
        )

    if aid == "eia":
        if eid == "metadata":
            return (
                _example(endpoint, "Root route metadata", "Inspect a top-level v2 route.", path_params={"route": "electricity"}, expected="Route metadata including child routes and facets.", variant="route-metadata"),
                _example(endpoint, "RTO route metadata", "Discover facets and data columns for a route.", path_params={"route": "electricity/rto/region-data"}, expected="Metadata for the RTO region-data route.", variant="facet-discovery"),
                _example(endpoint, "Petroleum route metadata", "Inspect another EIA route.", path_params={"route": "petroleum/pri/gnd"}, expected="Route metadata for petroleum price data.", variant="route-variant"),
            )
        if eid == "data":
            retail_route = {"route": "electricity/retail-sales"}
            return (
                _example(endpoint, "Monthly retail sales", "Fetch a compact retail-sales data page.", path_params=retail_route, query={"frequency": "monthly", "data[]": ["price"], "facets[sectorid][]": ["RES"], "facets[stateid][]": ["CO"], "start": "2024-01", "end": "2024-03", "length": 5}, expected="Rows for Colorado residential electricity prices.", variant="route-data"),
                _example(endpoint, "Sorted retail sales", "Sort route data by period.", path_params=retail_route, query={"frequency": "monthly", "data[]": ["price"], "facets[sectorid][]": ["RES"], "facets[stateid][]": ["CO"], "sort[0][column]": "period", "sort[0][direction]": "desc", "offset": 0, "length": 5}, expected="Recent Colorado residential electricity price rows.", variant="sorting"),
                _example(endpoint, "Annual retail sales", "Use an annual frequency route request.", path_params=retail_route, query={"frequency": "annual", "data[]": ["price"], "facets[sectorid][]": ["RES"], "facets[stateid][]": ["CO"], "start": "2020", "end": "2022", "length": 5}, expected="Annual Colorado residential electricity price rows.", variant="frequency-variant"),
            )
        return (
            _example(endpoint, "Legacy electricity series", "Fetch a legacy EIA series ID.", expected="Series metadata and observations for the legacy series.", variant="legacy-series"),
            _example(endpoint, "Legacy petroleum series", "Fetch a petroleum legacy series.", path_params={"series_id": "PET.EMM_EPM0_PTE_NUS_DPG.W"}, expected="Legacy petroleum series response where available.", variant="series-variant"),
            _example(endpoint, "Legacy series health check", "Use series ID lookup for compatibility.", expected="A legacy series response or clear upstream error for deprecated IDs.", variant="compatibility"),
        )

    if aid == "epa":
        if eid == "facility_report":
            return (
                _example(endpoint, "Facility report by registry ID", "Fetch a detailed facility report.", query={"output": "JSON", "p_id": "110000490174"}, expected="Detailed facility report for the identifier when found.", variant="facility-detail"),
                _example(endpoint, "Facility report XML", "Request another supported output format.", query={"output": "XML", "p_id": "110000490174"}, expected="XML facility report where supported.", variant="format-variant"),
                _example(endpoint, "Program facility report", "Use a program identifier where accepted.", query={"output": "JSON", "p_id": "CA0000000"}, expected="Detailed report or upstream no-match response.", variant="identifier-variant"),
            )
        return (
            _example(endpoint, "Facilities by state", "Search regulated facilities by state.", query={"output": "JSON", "p_st": "NC", "responseset": 1}, expected="Facility records and pagination metadata.", variant="state-filter"),
            _example(endpoint, "Facilities by ZIP", "Search facilities near a ZIP code.", query={"output": "JSON", "p_zip": "27701", "responseset": 1}, expected="Facility records matching the ZIP filter.", variant="zip-filter"),
            _example(endpoint, "Active facilities", "Request active facilities where supported.", query={"output": "JSON", "p_st": "CA", "p_act": "Y", "responseset": 1}, expected="Active facility records in the selected state.", variant="activity-filter"),
        )

    if aid == "fcc":
        if eid == "block_find":
            return (
                _example(endpoint, "Find block by lat/lon", "Resolve a point to a census block.", query={"latitude": 38.8977, "longitude": -77.0365, "format": "json"}, expected="Census block FIPS and related geography for the point.", variant="point-lookup"),
                _example(endpoint, "2020 census block", "Specify Census vintage.", query={"latitude": 34.0522, "longitude": -118.2437, "censusYear": 2020, "format": "json"}, expected="2020 block information for the point.", variant="census-year"),
                _example(endpoint, "XML block lookup", "Request XML output where supported.", query={"latitude": 40.7128, "longitude": -74.006, "format": "xml"}, expected="Block lookup in XML format.", variant="format-variant"),
            )
        return (
            _example(endpoint, "Area by point", "Fetch area information for a coordinate.", query={"lat": 38.8977, "lon": -77.0365, "format": "json"}, expected="Area response for the point.", variant="point-area"),
            _example(endpoint, "Area for 2020 vintage", "Specify Census vintage.", query={"lat": 34.0522, "lon": -118.2437, "censusYear": 2020, "format": "json"}, expected="Area response using 2020 Census geography.", variant="census-year"),
            _example(endpoint, "Area XML", "Request XML output where supported.", query={"lat": 40.7128, "lon": -74.006, "format": "xml"}, expected="Area response in XML.", variant="format-variant"),
        )

    if aid == "fdic":
        examples = {
            "institutions": ("STALP:NC", "NAME,CERT,STALP,ASSET", "Search NC institutions"),
            "locations": ("STALP:NC", "NAME,ADDRESS,CITY,STALP", "Search NC branch locations"),
            "financials": ("REPDTE:20231231", "CERT,REPDTE,ASSET,DEP", "Query financials for a report date"),
            "summary": ("STNAME:North Carolina", "STNAME,ACTIVE,ASSET", "Query state summary data"),
            "failures": ("FAILYR:2023", "NAME,CERT,FAILDATE,CITYST", "Query failed banks"),
        }[eid]
        filters, fields, label = examples
        return (
            _example(endpoint, label, "Fetch a compact FDIC page.", query={"filters": filters, "fields": fields, "limit": 5, "format": "json"}, expected="FDIC records with selected fields and metadata.", variant="filtered-page"),
            _example(endpoint, "Sorted FDIC page", "Sort a compact FDIC result page.", query={"fields": fields, "sort_by": fields.split(",")[0], "sort_order": "ASC", "limit": 5, "format": "json"}, expected="Sorted FDIC records.", variant="sorted-page"),
            _example(endpoint, "Second FDIC page", "Use offset pagination.", query={"filters": filters, "fields": fields, "limit": 5, "offset": 5, "format": "json"}, expected="Second page of FDIC records.", variant="pagination"),
        )

    if aid == "fec":
        if eid == "elections":
            return (
                _example(endpoint, "Presidential elections", "Fetch a compact OpenFEC presidential election page.", query={"office": "president", "cycle": 2024, "per_page": 5}, expected="Presidential election metadata with pagination metadata.", variant="presidential-page"),
                _example(endpoint, "Senate elections by state", "Fetch a compact Senate election page for one state.", query={"office": "senate", "cycle": 2024, "state": "CA", "per_page": 5}, expected="Senate election metadata for the selected state.", variant="senate-state"),
                _example(endpoint, "House elections by district", "Filter House elections by state and district.", query={"office": "house", "cycle": 2024, "state": "CA", "district": "12", "per_page": 5}, expected="House election metadata for the selected district.", variant="district-filter"),
            )
        fec_queries = {
            "candidates": ({"office": "P", "election_year": 2024, "per_page": 5}, "Presidential candidates"),
            "committees": ({"committee_type": "P", "per_page": 5}, "Political committees"),
            "schedule_a": ({"two_year_transaction_period": 2024, "committee_id": "C00580100", "per_page": 5}, "Itemized receipts"),
            "schedule_b": ({"two_year_transaction_period": 2024, "committee_id": "C00580100", "per_page": 5}, "Itemized disbursements"),
            "filings": ({"form_type": "F3", "per_page": 5}, "FEC filings"),
        }
        query, label = fec_queries[eid]
        return (
            _example(endpoint, label, "Fetch a compact OpenFEC page.", query=query, expected="OpenFEC records with pagination metadata.", variant="filtered-page"),
            _example(endpoint, "Sorted OpenFEC page", "Sort a compact result page.", query={**query, "sort": "-election_year"}, expected="Sorted OpenFEC records where the sort field is supported.", variant="sort"),
            _example(endpoint, "Date-filtered OpenFEC page", "Add a date range where supported.", query={**query, "min_date": "2024-01-01", "max_date": "2024-12-31"}, expected="Records constrained by date when the endpoint supports dates.", variant="date-filter"),
        )

    if aid == "ftc":
        if eid == "dnc_complaint":
            return (
                _example(endpoint, "Complaint by ID", "Fetch one complaint record by ID.", path_params={"id": "1"}, expected="One complaint record or upstream not-found response.", variant="identifier-lookup"),
                _example(endpoint, "Another complaint ID", "Use direct ID lookup for a second record.", path_params={"id": "2"}, expected="One complaint record or upstream not-found response.", variant="identifier-variant"),
                _example(endpoint, "Complaint detail health check", "Check detail endpoint shape with a small request.", path_params={"id": "3"}, expected="Detail response shape for a complaint identifier.", variant="health-check"),
            )
        if eid == "hsr_early_termination_notices":
            return (
                _example(endpoint, "Recent HSR notices", "Fetch the default HSR early termination notices response.", expected="HSR early termination notice records.", variant="row-page"),
                _example(endpoint, "HSR notice health check", "Use the endpoint as a low-volume availability check.", expected="HSR early termination notice response shape.", variant="health-check"),
                _example(endpoint, "HSR notice keyed request", "Exercise the API-keyed route without stale Socrata paging.", expected="HSR records without pagination validation errors.", variant="auth-check"),
            )
        return (
            _example(endpoint, "Recent FTC rows", "Fetch a small Socrata-style page.", query={"$limit": 5, "$offset": 0}, expected="FTC records with endpoint-specific fields.", variant="row-page"),
            _example(endpoint, "Selected FTC fields", "Project a few fields where supported.", query={"$limit": 5, "$select": "*"}, expected="Selected FTC fields or upstream validation feedback.", variant="field-projection"),
            _example(endpoint, "Ordered FTC rows", "Apply a lightweight ordering expression.", query={"$limit": 5, "$order": ":id"}, expected="Ordered FTC rows where the field exists.", variant="ordering"),
        )

    if aid == "fda":
        queries = {
            "drug_label": {"search": "openfda.brand_name:aspirin", "limit": 3},
            "drug_event": {"search": "receivedate:[20240101+TO+20240131]", "limit": 3},
            "drug_enforcement": {"search": "classification:\"Class II\"", "limit": 3},
            "device_event": {"limit": 3},
            "food_enforcement": {"search": "classification:\"Class II\"", "limit": 3},
        }
        sort_fields = {
            "drug_label": "effective_time:desc",
            "drug_event": "receivedate:desc",
            "drug_enforcement": "report_date:desc",
            "device_event": "",
            "food_enforcement": "report_date:desc",
        }
        return (
            _example(endpoint, "Basic openFDA search", "Run a low-volume search.", query=queries[eid], expected="openFDA result records and metadata.", variant="search"),
            _example(endpoint, "openFDA count", "Aggregate by a common field.", query={"count": "openfda.manufacturer_name.exact", "limit": 1}, expected="Count buckets when the field exists for the dataset.", variant="count"),
            _example(endpoint, "Sorted openFDA records", "Request recent records where date fields exist.", query={**queries[eid], **({"sort": sort_fields[eid]} if sort_fields[eid] else {})}, expected="Sorted records or upstream validation feedback if a date field differs.", variant="sort"),
        )

    if aid == "gsa":
        return (
            _example(endpoint, "API directory", "Fetch the GSA API directory landing page.", expected="HTML or directory metadata for GSA APIs.", variant="directory"),
            _example(endpoint, "Directory health check", "Use the endpoint as a low-volume availability check.", expected="GSA API directory content.", variant="health-check"),
            _example(endpoint, "API discovery", "Discover GSA-operated APIs before passthrough.", expected="Directory content with API links.", variant="discovery"),
        )

    if aid == "govinfo":
        if eid == "collections":
            return (
                _example(endpoint, "Recent Congressional Record collection", "List packages in a collection since a timestamp.", query={"pageSize": 5, "offsetMark": "*"}, expected="Package summaries and pagination cursor.", variant="collection-packages"),
                _example(endpoint, "Federal Register collection", "Use another collection code.", path_params={"collection": "FR", "start_date": "2018-08-01T00:00:00Z"}, query={"pageSize": 5, "offsetMark": "*"}, expected="Federal Register package summaries.", variant="collection-variant"),
                _example(endpoint, "Collection cursor request", "Use a compact page for cursor-based pagination.", query={"pageSize": 5, "offsetMark": "*"}, expected="Package list with next offset marker.", variant="pagination"),
            )
        if eid == "package_summary":
            return (
                _example(endpoint, "Congressional Record summary", "Fetch summary metadata for one package.", expected="Package-level metadata and content links.", variant="package-summary"),
                _example(endpoint, "Federal Register summary", "Fetch summary metadata for another package.", path_params={"package_id": "FR-2018-08-03"}, expected="Federal Register package summary.", variant="package-variant"),
                _example(endpoint, "Congressional Record summary variant", "Fetch summary metadata for a CREC package.", path_params={"package_id": "CREC-2018-10-10"}, expected="Congressional Record package summary.", variant="package-variant"),
            )
        if eid == "package_granules":
            return (
                _example(endpoint, "Congressional Record granules", "List granules inside one package.", query={"pageSize": 5, "offsetMark": "*"}, expected="Granule records and pagination cursor.", variant="granule-list"),
                _example(endpoint, "Granules with offset", "Use offset pagination where supported.", query={"pageSize": 5, "offset": 0}, expected="Granule records from the first offset page.", variant="offset-pagination"),
                _example(endpoint, "Granule pagination", "Use cursor pagination.", query={"pageSize": 5, "offsetMark": "*"}, expected="First page of granules with next cursor.", variant="pagination"),
            )
        return (
            _example(endpoint, "Search bills", "Search govinfo with a compact page.", body={"query": "climate", "pageSize": 5, "offsetMark": "*"}, expected="Search hits across packages and granules.", variant="search"),
            _example(endpoint, "Search phrase", "Use a phrase query.", body={"query": "\"Federal Register\"", "pageSize": 5, "offsetMark": "*"}, expected="Search hits matching the phrase.", variant="phrase-search"),
            _example(endpoint, "Search with sort", "Apply a sort definition.", body={"query": "budget", "pageSize": 5, "offsetMark": "*", "sorts": [{"field": "dateIssued", "sortOrder": "DESC"}]}, expected="Sorted search hits where supported.", variant="sorted-search"),
        )

    if aid == "loc":
        if eid == "bill_detail":
            return (
                _example(endpoint, "Bill detail", "Fetch one Congress.gov bill.", query={"format": "json"}, expected="Bill metadata, titles, actions, and links.", variant="bill-detail"),
                _example(endpoint, "Senate bill detail", "Fetch a Senate bill by path params.", path_params={"congress": 118, "bill_type": "s", "bill_number": 1}, query={"format": "json"}, expected="Bill detail response for the Senate bill.", variant="bill-type-variant"),
                _example(endpoint, "Resolution detail", "Fetch a resolution by path params.", path_params={"congress": 118, "bill_type": "hjres", "bill_number": 1}, query={"format": "json"}, expected="Resolution detail response when available.", variant="resolution-detail"),
            )
        loc_queries = {
            "bill": {"congress": 118, "limit": 5, "format": "json"},
            "member": {"limit": 5, "format": "json"},
            "committee": {"congress": 118, "limit": 5, "format": "json"},
            "hearing": {"congress": 118, "limit": 5, "format": "json"},
            "nomination": {"congress": 118, "limit": 5, "format": "json"},
        }
        return (
            _example(endpoint, f"List {eid}", "Fetch a compact Congress.gov list page.", query=loc_queries[eid], expected="Congress.gov records and pagination metadata.", variant="list"),
            _example(endpoint, f"Updated {eid}", "Filter by update timestamps where supported.", query={**loc_queries[eid], "fromDateTime": "2024-01-01T00:00:00Z"}, expected="Records updated after the timestamp where supported.", variant="updated-filter"),
            _example(endpoint, f"Second {eid} page", "Use offset pagination.", query={**loc_queries[eid], "offset": 5}, expected="Second page of Congress.gov records.", variant="pagination"),
        )

    if aid == "nih_reporter":
        if eid == "projects_search":
            return (
                _example(endpoint, "Recent cancer projects", "Search projects with compact include fields.", body={"criteria": {"fiscal_years": [2025], "terms": "cancer"}, "include_fields": ["ApplId", "ProjectTitle", "AwardAmount", "Organization"], "offset": 0, "limit": 5}, expected="Project records and total count.", variant="project-search"),
                _example(endpoint, "Projects by organization", "Use organization criteria and selected fields.", body={"criteria": {"org_names": ["JOHNS HOPKINS UNIVERSITY"], "fiscal_years": [2024]}, "include_fields": ["ApplId", "ProjectTitle", "PrincipalInvestigators"], "limit": 5}, expected="Project records for the organization criteria.", variant="organization-filter"),
                _example(endpoint, "Sorted projects", "Sort project results by award amount.", body={"criteria": {"fiscal_years": [2024]}, "include_fields": ["ApplId", "AwardAmount", "ProjectTitle"], "sort_field": "AwardAmount", "sort_order": "desc", "limit": 5}, expected="Sorted project records where sort field is accepted.", variant="sort"),
            )
        return (
            _example(endpoint, "Publication search by term", "Search publications tied to reported projects.", body={"criteria": {"terms": "genomics", "publication_years": [2024]}, "include_fields": ["Pmid", "Title", "Journal"], "offset": 0, "limit": 5}, expected="Publication records and total count.", variant="publication-search"),
            _example(endpoint, "Publications by project year", "Filter publication search with fiscal years.", body={"criteria": {"fiscal_years": [2023], "terms": "vaccine"}, "include_fields": ["Pmid", "Title", "CoreProjectNum"], "limit": 5}, expected="Publication records matching the criteria.", variant="criteria-variant"),
            _example(endpoint, "Publications exclude fields", "Demonstrate compact include/exclude usage.", body={"criteria": {"terms": "diabetes"}, "include_fields": ["Pmid", "Title"], "exclude_fields": ["Abstract"], "limit": 5}, expected="Publication records with compact field selection.", variant="field-selection"),
        )

    if aid == "nrel":
        if eid == "pvwatts_v8":
            body = {"lat": 39.7392, "lon": -104.9903, "system_capacity": 4, "module_type": 0, "losses": 14, "array_type": 1, "tilt": 20, "azimuth": 180}
            return (
                _example(endpoint, "Denver PVWatts", "Run a low-volume PVWatts model.", query=body, expected="PVWatts AC output, solar radiation, and station metadata.", variant="solar-model"),
                _example(endpoint, "Hourly PVWatts", "Request hourly output for one site.", query={**body, "timeframe": "hourly"}, expected="Hourly PVWatts output arrays.", variant="hourly-model"),
                _example(endpoint, "Fixed roof PVWatts", "Use a fixed roof array type.", query={**body, "array_type": 0, "tilt": 30}, expected="PVWatts output for a fixed array.", variant="array-variant"),
            )
        if eid == "alt_fuel_nearest":
            return (
                _example(endpoint, "Nearest EV stations", "Find nearby electric charging stations.", query={"latitude": 39.7392, "longitude": -104.9903, "fuel_type": "ELEC", "radius": 5, "limit": 5}, expected="Nearest station records and distances.", variant="nearest"),
                _example(endpoint, "Nearest CNG stations", "Find nearby CNG stations.", query={"latitude": 34.0522, "longitude": -118.2437, "fuel_type": "CNG", "radius": 10, "limit": 5}, expected="Nearest CNG station records.", variant="fuel-type"),
                _example(endpoint, "Nearest stations by ZIP", "Use ZIP input where supported.", query={"zip": "80202", "fuel_type": "ELEC", "radius": 5, "limit": 5}, expected="Nearest station records near the ZIP.", variant="zip-nearest"),
            )
        return (
            _example(endpoint, "EV stations by state", "Search alternative fuel stations by state.", query={"state": "CO", "fuel_type": "ELEC", "limit": 5}, expected="Station records for the selected state and fuel.", variant="state-filter"),
            _example(endpoint, "Hydrogen stations", "Search for a fuel type.", query={"fuel_type": "HY", "limit": 5}, expected="Hydrogen station records where available.", variant="fuel-type"),
            _example(endpoint, "Stations by ZIP", "Search stations near a ZIP code.", query={"zip": "94103", "fuel_type": "ELEC", "limit": 5}, expected="Station records near the ZIP.", variant="zip-filter"),
        )

    if aid == "fred":
        if eid == "series_search":
            return (
                _example(endpoint, "Search GDP series", "Find FRED series matching GDP.", query={"search_text": "gross domestic product", "limit": 5}, expected="Series search results with IDs, titles, units, and frequencies.", variant="series-search"),
                _example(endpoint, "Search with tags", "Constrain search by tags.", query={"search_text": "unemployment", "tag_names": "monthly;usa", "limit": 5}, expected="Tagged series search results.", variant="tag-filter"),
                _example(endpoint, "Search with offset", "Page through FRED search results.", query={"search_text": "inflation", "limit": 5, "offset": 5}, expected="Second page of series search results.", variant="pagination"),
            )
        if eid == "series":
            return (
                _example(endpoint, "GDP metadata", "Fetch metadata for one FRED series.", query={"series_id": "GDP"}, expected="Series metadata including units, frequency, and dates.", variant="series-metadata"),
                _example(endpoint, "CPI metadata", "Fetch metadata for CPI.", query={"series_id": "CPIAUCSL"}, expected="CPI series metadata.", variant="series-variant"),
                _example(endpoint, "Unemployment metadata", "Fetch metadata for unemployment rate.", query={"series_id": "UNRATE"}, expected="Unemployment rate series metadata.", variant="series-variant"),
            )
        if eid == "series_observations":
            return (
                _example(endpoint, "GDP observations", "Fetch recent GDP observations.", query={"series_id": "GDP", "observation_start": "2020-01-01", "limit": 5}, expected="Observation rows with dates and values.", variant="observations"),
                _example(endpoint, "CPI percent change", "Fetch transformed CPI observations.", query={"series_id": "CPIAUCSL", "units": "pc1", "observation_start": "2023-01-01", "limit": 5}, expected="CPI observations transformed to percent change from year ago.", variant="units-transform"),
                _example(endpoint, "Monthly aggregation", "Fetch aggregated observations where supported.", query={"series_id": "GDP", "frequency": "a", "aggregation_method": "avg", "limit": 5}, expected="Aggregated observation rows.", variant="frequency-aggregation"),
            )
        if eid == "category":
            return (
                _example(endpoint, "Root category", "Fetch a FRED category.", query={"category_id": 0}, expected="Category metadata.", variant="category"),
                _example(endpoint, "Money banking category", "Fetch another category.", query={"category_id": 32991}, expected="Category metadata where ID exists.", variant="category-variant"),
                _example(endpoint, "Population category", "Fetch category metadata for a common topic.", query={"category_id": 104}, expected="Category metadata where ID exists.", variant="category-variant"),
            )
        if eid == "category_children":
            return (
                _example(endpoint, "Root category children", "List child categories.", query={"category_id": 0}, expected="Child category records.", variant="children"),
                _example(endpoint, "Economic categories", "List child categories for an economic category.", query={"category_id": 32991}, expected="Child category records where ID exists.", variant="children-variant"),
                _example(endpoint, "Default children", "Call children endpoint with defaults where supported.", query={}, expected="Child category records or default root children.", variant="root-default"),
            )
        if eid == "releases":
            return (
                _example(endpoint, "List releases", "Fetch a compact release list.", query={"limit": 5}, expected="FRED release records.", variant="release-list"),
                _example(endpoint, "Releases page two", "Page through releases.", query={"limit": 5, "offset": 5}, expected="Second page of release records.", variant="pagination"),
                _example(endpoint, "Sorted releases", "Sort releases by name where supported.", query={"limit": 5, "sort_order": "asc"}, expected="Sorted release records.", variant="sort"),
            )
        if eid == "release":
            return (
                _example(endpoint, "GDP release metadata", "Fetch release metadata.", query={"release_id": 53}, expected="Release metadata for GDP and related series.", variant="release-metadata"),
                _example(endpoint, "Employment situation release", "Fetch another release.", query={"release_id": 50}, expected="Release metadata where ID exists.", variant="release-variant"),
                _example(endpoint, "CPI release", "Fetch CPI release metadata.", query={"release_id": 10}, expected="Release metadata where ID exists.", variant="release-variant"),
            )
        if eid == "release_series":
            return (
                _example(endpoint, "GDP release series", "List series in one release.", query={"release_id": 53, "limit": 5}, expected="Series records attached to the release.", variant="release-series"),
                _example(endpoint, "Employment release series", "List series in another release.", query={"release_id": 50, "limit": 5}, expected="Release series records where ID exists.", variant="release-variant"),
                _example(endpoint, "Paged release series", "Page through release series.", query={"release_id": 53, "limit": 5, "offset": 5}, expected="Second page of release series records.", variant="pagination"),
            )
        return (
            _example(endpoint, "GDP release observations", "Fetch FRED v2 release observations.", query={"release_id": 53, "observation_start": "2024-01-01", "limit": 5}, expected="Bulk observations for series in the release.", variant="release-observations"),
            _example(endpoint, "Release observations range", "Use a bounded date range.", query={"release_id": 53, "observation_start": "2023-01-01", "observation_end": "2023-12-31", "limit": 5}, expected="Release observations in the requested date range.", variant="date-range"),
            _example(endpoint, "Paged release observations", "Page through release observations.", query={"release_id": 53, "limit": 5, "offset": 5}, expected="Second page of release observations.", variant="pagination"),
        )

    if aid == "datausa":
        if eid == "data":
            return (
                _example(endpoint, "Population by state", "Fetch a Data USA population measure.", query={"cube": "acs_yg_total_population_5", "drilldowns": "State,Year", "measures": "Population", "include": "Year:2023", "limit": "100,0"}, expected="State-level population rows.", variant="measure-query"),
                _example(endpoint, "County population", "Fetch county drilldown data.", query={"cube": "acs_yg_total_population_5", "drilldowns": "County,Year", "measures": "Population", "include": "Year:2023", "limit": "10,0"}, expected="County population rows.", variant="geography-drilldown"),
                _example(endpoint, "Sorted population", "Sort a population measure.", query={"cube": "acs_yg_total_population_5", "drilldowns": "State,Year", "measures": "Population", "include": "Year:2023", "sort": "Population.desc", "limit": "5,0"}, expected="Population rows sorted by population.", variant="measure-variant"),
            )
        return (
            _example(endpoint, "List cubes", "List Data USA Tesseract cubes.", expected="Cube metadata useful for selecting a dataset.", variant="dimension-search"),
            _example(endpoint, "Cube discovery", "Discover available datasets before querying records.", expected="Tesseract cube inventory.", variant="dimension-variant"),
            _example(endpoint, "Discovery health check", "Use cube listing as a low-volume health check.", expected="Tesseract cube inventory.", variant="generic-search"),
        )

    if aid == "ipums":
        if eid == "create_extract":
            return (
                _example(
                    endpoint,
                    "CPS ASEC extract",
                    "Submit a microdata extract for CPS ASEC samples.",
                    query={"collection": "cps"},
                    body={"description": "CPS ASEC example", "dataStructure": {"rectangular": {"on": "P"}}, "dataFormat": "csv", "samples": {"cps2018_03s": {}, "cps2019_03s": {}}, "variables": {"AGE": {}, "SEX": {}, "RACE": {}, "STATEFIP": {}}},
                    expected="Queued extract response with number, status, extractDefinition, and downloadLinks when complete.",
                    variant="microdata-extract",
                ),
                _example(
                    endpoint,
                    "ATUS time-use extract",
                    "Submit an ATUS extract with time-use variables.",
                    query={"collection": "atus"},
                    body={"description": "ATUS time use example", "dataStructure": {"hierarchical": {}}, "dataFormat": "fixed_width", "samples": {"at2017": {}}, "timeUseVariables": {"BLS_PCARE": {}}, "variables": {"ECAGE": {}}},
                    expected="Queued extract response for an ATUS collection request.",
                    variant="time-use-extract",
                ),
                _example(
                    endpoint,
                    "NHGIS ACS table extract",
                    "Submit an NHGIS aggregate/spatial extract.",
                    query={"collection": "nhgis"},
                    body={"description": "NHGIS ACS example", "dataFormat": "csv_header", "datasets": {"2017_2021_ACS5a": {"dataTables": ["B01001"], "geogLevels": ["state"], "years": ["2021"]}}},
                    expected="Queued NHGIS extract response with extract number.",
                    variant="aggregate-extract",
                ),
            )
        if eid in {"extracts", "extract"}:
            return (
                _example(endpoint, "Check CPS extract", "Fetch status for a CPS extract.", path_params={"extract_number": 1}, query={"collection": "cps"}, expected="Status such as queued, started, produced, failed, or completed.", variant="status"),
                _example(endpoint, "List recent NHGIS extracts", "List recent NHGIS extracts.", query={"collection": "nhgis", "limit": 5}, expected="Recent extract request records.", variant="history"),
                _example(endpoint, "Check ATUS extract", "Fetch status for an ATUS extract.", path_params={"extract_number": 3}, query={"collection": "atus"}, expected="Status and downloadLinks when complete.", variant="time-use-status"),
            )
        if eid.startswith("metadata_"):
            return (
                _example(endpoint, "NHGIS datasets", "List NHGIS datasets.", path_params={"dataset_name": "2017_2021_ACS5a"}, query={"collection": "nhgis", "pageSize": 5}, expected="Dataset metadata page.", variant="nhgis-metadata"),
                _example(endpoint, "NHGIS ACS dataset", "Fetch one NHGIS dataset record.", path_params={"dataset_name": "2017_2021_ACS5a"}, query={"collection": "nhgis"}, expected="Dataset record with data tables and geography levels where endpoint supports dataset detail.", variant="dataset-detail"),
                _example(endpoint, "IHGIS metadata", "List IHGIS datasets or tables.", path_params={"dataset_name": "can1971"}, query={"collection": "ihgis", "pageSize": 5}, expected="IHGIS metadata records where available.", variant="ihgis-metadata"),
            )
        if eid == "download":
            return (
                _example(endpoint, "Download data file", "Fetch the data file path from an IPUMS downloadLinks URL.", path_params={"download_path": "cps/api/v1/extracts/590142/cps_00001.csv.gz"}, expected="File response from IPUMS when the link is authorized; prefer govdata_get_dataset(action='download_file') to save bytes.", variant="data-file"),
                _example(endpoint, "Download codebook", "Fetch a codebook path from downloadLinks.", path_params={"download_path": "cps/api/v1/extracts/590142/cps_00001.cbk"}, expected="Codebook file response.", variant="codebook"),
                _example(endpoint, "Download NHGIS zip", "Fetch an NHGIS extract zip path.", path_params={"download_path": "nhgis/api/v1/extracts/9123456/nhgis0006_csv.zip"}, expected="ZIP file response.", variant="zip"),
            )
        return (
            _example(endpoint, "NHGIS crosswalk", "Fetch an NHGIS supplemental crosswalk asset.", path_params={"supplemental_path": "nhgis/crosswalks/nhgis_blk2010_blk2020_25.zip"}, expected="Supplemental file response.", variant="crosswalk"),
            _example(endpoint, "NHGIS environmental data", "Fetch an environmental supplemental asset path.", path_params={"supplemental_path": "nhgis/environmental/example.zip"}, expected="Supplemental file response where path exists.", variant="environmental"),
            _example(endpoint, "NHGIS estimates", "Fetch an estimates supplemental asset path.", path_params={"supplemental_path": "nhgis/estimates/example.zip"}, expected="Supplemental file response where path exists.", variant="estimates"),
        )

    return (
        _example(endpoint, "Compact request", "Make a low-volume request.", query={"limit": 5}, expected="Endpoint-specific response envelope.", variant="default"),
        _example(endpoint, "Paginated request", "Use basic pagination where supported.", query={"limit": 5, "offset": 5}, expected="Second page where supported.", variant="pagination"),
        _example(endpoint, "Metadata request", "Inspect endpoint response shape.", expected="Endpoint-specific metadata or records.", variant="metadata"),
    )


_AGENCY_GOTCHAS: dict[str, tuple[str, ...]] = {
    "agriculture": ("FoodData Central examples omit API keys; the MCP injects api.data.gov credentials when configured.",),
    "census": ("Census variable IDs, geographies, and datasets are dynamic; inspect metadata endpoints before data calls.",),
    "bls": ("Unregistered BLS usage has lower daily, series, and year-span limits than registered-key usage.",),
    "usaspending": ("USAspending search endpoints expect JSON POST bodies, not query-string filters.",),
    "education": ("College Scorecard exposes many field names; use the data dictionary for uncommon fields.",),
    "justice": ("FBI Crime Data Explorer estimates routes are kept for compatibility; summarized CDE routes use offense slugs and MM-YYYY date bounds.",),
    "justice_ncvs": ("NCVS select datasets use Socrata-style query parameters; send the api.data.gov key in the X-Api-Key header, not as api_key.",),
    "justice_crimesolutions": ("CrimeSolutions program and practice feeds currently return CSV content.",),
    "justice_fara": ("FARA documents a 5 requests per 10 seconds throttle; the MCP spaces FARA requests by 3 seconds and does not inject API_DATA_GOV_KEY because current FARA docs list v1 endpoints as unauthenticated.",),
    "treasury": ("Fiscal Data filters are expression strings such as field:operator:value.",),
    "eia": ("EIA API v2 route facets, frequencies, and data columns vary by route.",),
    "epa": ("EPA ECHO parameters are program-specific and often use p_* names.",),
    "fec": ("OpenFEC examples omit api_key because the MCP injects it from environment variables.",),
    "fda": ("openFDA search syntax is fielded; unknown fields produce upstream validation errors.",),
    "nih_reporter": ("Keep RePORTER limit values at or below 500 and avoid request bursts.",),
    "fred": ("FRED endpoints require FRED_API_KEY and default to file_type=json in the MCP.",),
    "ipums": ("IPUMS requires IPUMS_API_KEY, an IPUMS account, and collection registration. Extracts are asynchronous and metadata support differs by collection.",),
}


def _gotchas_for(agency: Agency, endpoint: Endpoint) -> tuple[str, ...]:
    gotchas = list(_AGENCY_GOTCHAS.get(agency.id, ()))
    if endpoint.auth != "none":
        gotchas.append("Do not put API keys in examples or user-visible logs; the MCP injects configured credentials.")
    if endpoint.method == "POST":
        gotchas.append("Send request payloads as JSON bodies.")
    return tuple(dict.fromkeys(gotchas))


def _docs_urls_for(agency: Agency, endpoint: Endpoint) -> tuple[str, ...]:
    urls: list[str] = []
    for url in (endpoint.docs_url, agency.docs_url):
        if url and url not in urls:
            urls.append(url)
    return tuple(urls)


def _build_endpoint_docs() -> dict[tuple[str, str], EndpointDoc]:
    docs: dict[tuple[str, str], EndpointDoc] = {}
    for agency in AGENCIES.values():
        if agency.status != "active" or agency.id in CANONICAL_AGENCY_IDS:
            continue
        for endpoint in agency.endpoints.values():
            if endpoint.status != "active":
                continue
            examples = _examples_for(agency, endpoint)
            if len(examples) != 3:
                raise AssertionError(f"{agency.id}/{endpoint.id} must have exactly 3 examples.")
            docs[(agency.id, endpoint.id)] = EndpointDoc(
                schema=_schema_for(agency, endpoint),
                examples=examples,
                common_gotchas=_gotchas_for(agency, endpoint),
                official_docs_urls=_docs_urls_for(agency, endpoint),
            )
    return docs


ENDPOINT_DOCS = _build_endpoint_docs()
