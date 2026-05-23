from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from .diagnostics import diagnostic
from .ipums import detect_ipums_collections, download_intent
from .registry import AGENCIES, Endpoint, get_agency
from .request_shapes import RequestShapeError, normalize_endpoint_request


RouteAction = Literal["raw", "download_plan"]

PATH_VAR_RE = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)}")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
CENSUS_VARIABLE_RE = re.compile(r"\b[A-Z]\d{5}_\d{3}[A-Z]?\b")
BLS_SERIES_RE = re.compile(r"\b[A-Z]{2}[A-Z0-9]{8,}\b")

FRED_SERIES_ALIASES = {
    "gross domestic product": "GDP",
    "real gross domestic product": "GDPC1",
    "unemployment rate": "UNRATE",
    "federal funds rate": "FEDFUNDS",
}

ACS_VARIABLE_ALIASES = {
    "total population": "B01003_001E",
    "population": "B01003_001E",
    "median household income": "B19013_001E",
}

STATE_NAME_TO_ABBR = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}

FBI_OFFENSE_ALIASES = {
    "violent crime": "violent-crime",
    "violent-crime": "violent-crime",
    "property crime": "property-crime",
    "property-crime": "property-crime",
    "aggravated assault": "aggravated-assault",
    "homicide": "homicide",
    "murder": "homicide",
    "rape": "rape",
    "robbery": "robbery",
    "burglary": "burglary",
    "larceny": "larceny",
    "motor vehicle theft": "motor-vehicle-theft",
    "auto theft": "motor-vehicle-theft",
    "arson": "arson",
}


@dataclass(frozen=True)
class RouteCandidate:
    route_id: str
    action: RouteAction
    title: str
    confidence: float
    reasons: tuple[str, ...]
    agency_id: str | None = None
    endpoint_id: str | None = None
    path_params: dict[str, Any] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] | None = None
    required_inputs: tuple[str, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "route_id": self.route_id,
            "action": self.action,
            "title": self.title,
            "confidence": round(self.confidence, 3),
            "reasons": list(self.reasons),
            "required_inputs": list(self.required_inputs),
        }
        if self.agency_id:
            payload["agency_id"] = self.agency_id
        if self.endpoint_id:
            payload["endpoint_id"] = self.endpoint_id
        if self.path_params:
            payload["path_params"] = self.path_params
        if self.query:
            payload["query"] = self.query
        if self.body is not None:
            payload["body"] = self.body
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload


def plan_data_request(
    request: str,
    *,
    source_hint: str | None = None,
    route_id: str | None = None,
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Return a conservative route plan for a natural-language data request."""
    clean_request = " ".join(request.split())
    if not clean_request:
        return {
            "status": "needs_input",
            "request": request,
            "selected_route": None,
            "candidates": [],
            "warnings": ["request must describe the data to retrieve."],
            "diagnostics": [
                diagnostic("missing_required_input", "warning", "request must describe the data to retrieve.")
            ],
        }

    route_candidates = _route_from_explicit_id(
        route_id,
        clean_request,
        path_params=path_params,
        query=query,
        body=body,
        limit=limit,
    )
    if route_candidates is None:
        route_candidates = _infer_routes(
            clean_request,
            source_hint=source_hint,
            path_params=path_params or {},
            query=query or {},
            body=body,
            limit=limit,
        )

    candidates = _dedupe_and_sort(route_candidates)[: max(limit, 1)]
    if not candidates:
        return {
            "status": "needs_input",
            "request": clean_request,
            "selected_route": None,
            "candidates": [],
            "warnings": [
                "No confident GovData route was found. Add a source_hint, route_id, or more specific dataset/series/field details."
            ],
            "diagnostics": [
                diagnostic(
                    "missing_required_input",
                    "warning",
                    "No confident GovData route was found. Add a source_hint, route_id, or more specific dataset/series/field details.",
                )
            ],
        }

    selected = candidates[0]
    status = _planned_status(selected, candidates, explicit_route=route_id is not None)
    return {
        "status": status,
        "request": clean_request,
        "selected_route": selected.to_dict(),
        "candidates": [candidate.to_dict() for candidate in candidates],
        "warnings": _planning_warnings(status, selected, candidates),
        "diagnostics": list(selected.diagnostics),
    }


def _route_from_explicit_id(
    route_id: str | None,
    request: str,
    *,
    path_params: dict[str, Any] | None,
    query: dict[str, Any] | None,
    body: dict[str, Any] | None,
    limit: int,
) -> list[RouteCandidate] | None:
    if route_id is None:
        return None

    normalized = route_id.strip().lower().replace(":", ".")
    if normalized in {"govdata.download_plan", "download_plan", "ipums.download_plan"}:
        return [
            RouteCandidate(
                route_id="govdata.download_plan",
                action="download_plan",
                title="Plan an IPUMS or raw API download workflow",
                confidence=1.0,
                reasons=("route_id explicitly requested download planning.",),
                query={"prefer_ipums": True},
            )
        ]

    if "." not in normalized:
        return []
    agency_id, endpoint_id = normalized.split(".", 1)
    agency = AGENCIES.get(agency_id)
    if agency is None or endpoint_id not in agency.endpoints:
        return []
    endpoint = agency.endpoints[endpoint_id]
    return [
        _raw_candidate(
            agency_id,
            endpoint_id,
            endpoint,
            confidence=1.0,
            reasons=(f"route_id explicitly requested {agency_id}.{endpoint_id}.",),
            path_params=path_params or {},
            query=query or _default_query_for_request(agency_id, endpoint_id, request, limit),
            body=body,
        )
    ]


def _infer_routes(
    request: str,
    *,
    source_hint: str | None,
    path_params: dict[str, Any],
    query: dict[str, Any],
    body: dict[str, Any] | None,
    limit: int,
) -> list[RouteCandidate]:
    text = request.lower()
    hint = (source_hint or "").strip().lower()
    routes: list[RouteCandidate] = []

    if _matches_any(text, ("download", "extract", "microdata", "pums")):
        collections = detect_ipums_collections(request)
        if collections or "ipums" in hint or "ipums" in text:
            routes.append(
                RouteCandidate(
                    route_id="govdata.download_plan",
                    action="download_plan",
                    title="Plan an IPUMS or raw API download workflow",
                    confidence=0.93 if download_intent(request) else 0.82,
                    reasons=(
                        "request looks like a downloadable extract workflow.",
                        "IPUMS collection terms were detected." if collections else "IPUMS was named directly.",
                    ),
                    query={"prefer_ipums": True},
                )
            )

    routes.extend(_fred_routes(request, hint, query, limit))
    routes.extend(_bls_routes(request, hint, query, body))
    routes.extend(_census_routes(request, hint, path_params, query))
    routes.extend(_catalog_routes(request, hint, query, limit))
    routes.extend(_usaspending_routes(request, hint, body))
    routes.extend(_nih_routes(request, hint, body))
    routes.extend(_justice_routes(request, hint, path_params, query, limit))
    return routes


def _fred_routes(
    request: str,
    hint: str,
    query: dict[str, Any],
    limit: int,
) -> list[RouteCandidate]:
    text = request.lower()
    if not _matches_any(text, ("fred", "economic data", "gdp", "gross domestic product", "unemployment rate", "federal funds rate", "consumer price index", "cpi")) and hint != "fred":
        return []

    routes: list[RouteCandidate] = []
    series_id = str(query.get("series_id") or _fred_series_id(request) or "")
    start, end = _year_bounds(request)
    has_observation_intent = series_id and _matches_any(text, ("observation", "observations", "values", "data", "fetch", "get"))
    if has_observation_intent:
        fred_query: dict[str, Any] = {"series_id": series_id, "limit": query.get("limit", limit)}
        if start:
            fred_query["observation_start"] = query.get("observation_start", f"{start}-01-01")
        if end:
            fred_query["observation_end"] = query.get("observation_end", f"{end}-12-31")
        fred_query.update({key: value for key, value in query.items() if key not in {"search_text"}})
        routes.append(
            _raw_candidate(
                "fred",
                "series_observations",
                get_agency("fred").endpoints["series_observations"],
                confidence=0.94 if hint == "fred" or "fred" in text else 0.84,
                reasons=("FRED series observations match the request.",),
                query=fred_query,
            )
        )

    if has_observation_intent and not _matches_any(text, ("search", "find")):
        return routes

    search_text = query.get("search_text") or _search_phrase(request, remove_terms=("fred", "series", "search", "find"))
    routes.append(
        _raw_candidate(
            "fred",
            "series_search",
            get_agency("fred").endpoints["series_search"],
            confidence=0.9 if hint == "fred" or "fred" in text else 0.6 if _matches_any(text, ("consumer price index", "cpi")) else 0.72,
            reasons=("FRED was named or the request matches common FRED economic series terms.",),
            query={"search_text": search_text, "limit": query.get("limit", limit)},
        )
    )
    return routes


def _bls_routes(
    request: str,
    hint: str,
    query: dict[str, Any],
    body: dict[str, Any] | None,
) -> list[RouteCandidate]:
    text = request.lower()
    if not _matches_any(text, ("bls", "bureau of labor statistics", "cpi", "consumer price index", "cuur")) and hint != "bls":
        return []

    series_ids = _bls_series_ids(request, query, body)
    start, end = _year_bounds(request)
    payload: dict[str, Any] = dict(body or {})
    if series_ids:
        payload.setdefault("seriesid", series_ids)
    if start:
        payload.setdefault("startyear", str(start))
    if end:
        payload.setdefault("endyear", str(end))

    required: tuple[str, ...] = () if payload.get("seriesid") else ("series_ids or body.seriesid",)
    return [
        _raw_candidate(
            "bls",
            "timeseries",
            get_agency("bls").endpoints["timeseries"],
            confidence=0.94 if series_ids or hint == "bls" or "bls" in text else 0.61,
            reasons=("BLS time series terms or series IDs were detected.",),
            body=payload if payload else None,
            required_inputs=required,
        )
    ]


def _census_routes(
    request: str,
    hint: str,
    path_params: dict[str, Any],
    query: dict[str, Any],
) -> list[RouteCandidate]:
    text = request.lower()
    if not _matches_any(text, ("census", "acs", "american community survey", "county", "state", "population", "household income")) and hint != "census":
        return []

    year = path_params.get("year") or query.get("year") or _latest_year(request)
    dataset = path_params.get("dataset") or query.get("dataset") or _census_dataset(request)
    metadata = str(query.get("metadata") or "")
    if _matches_any(text, ("variables", "variable metadata")) or metadata == "variables":
        endpoint_id = "variables"
        route_query: dict[str, Any] = {}
    elif _matches_any(text, ("geography", "geographies")) or metadata == "geography":
        endpoint_id = "geography"
        route_query = {}
    else:
        endpoint_id = "data"
        route_query = _census_data_query(request, query)

    route_path_params = {"year": year, "dataset": dataset}
    required = tuple(
        name
        for name, value in {
            "year": year,
            "dataset": dataset,
        }.items()
        if value in {None, ""}
    )
    if endpoint_id == "data":
        if "get" not in route_query:
            required += ("variables or query.get",)
        if "for" not in route_query:
            required += ("geography or query.for",)

    return [
        _raw_candidate(
            "census",
            endpoint_id,
            get_agency("census").endpoints[endpoint_id],
            confidence=0.91 if "census" in text or "acs" in text or hint == "census" else 0.74,
            reasons=("Census/ACS data or metadata terms were detected.",),
            path_params=route_path_params,
            query=route_query,
            required_inputs=required,
        )
    ]


def _catalog_routes(
    request: str,
    hint: str,
    query: dict[str, Any],
    limit: int,
) -> list[RouteCandidate]:
    text = request.lower()
    if not _matches_any(text, ("data.gov", "catalog", "dataset", "datasets", "search for data", "find data")) and hint not in {"datagov", "data.gov", "catalog"}:
        return []
    q = str(query.get("q") or _search_phrase(request, remove_terms=("data.gov", "catalog", "dataset", "datasets", "search", "find")))
    catalog_query = {"q": q, "per_page": query.get("per_page", limit)}
    catalog_query.update({key: value for key, value in query.items() if key not in {"q", "per_page"}})
    return [
        _raw_candidate(
            "datagov",
            "search",
            get_agency("datagov").endpoints["search"],
            confidence=0.94 if hint in {"datagov", "data.gov", "catalog"} or "data.gov" in text else 0.86,
            reasons=("Data.gov catalog discovery terms were detected.",),
            query=catalog_query,
        )
    ]


def _usaspending_routes(
    request: str,
    hint: str,
    body: dict[str, Any] | None,
) -> list[RouteCandidate]:
    text = request.lower()
    if not _matches_any(text, ("usaspending", "usa spending", "federal spending", "federal award", "awards")) and hint != "usaspending":
        return []

    endpoint_id = "awards_last_updated" if "last updated" in text else "search_spending_by_award"
    required: tuple[str, ...] = ()
    if endpoint_id == "search_spending_by_award" and body is None:
        required = ("body.filters",)
    return [
        _raw_candidate(
            "usaspending",
            endpoint_id,
            get_agency("usaspending").endpoints[endpoint_id],
            confidence=0.92 if "usaspending" in text or hint == "usaspending" else 0.78,
            reasons=("USAspending/federal award terms were detected.",),
            body=body,
            required_inputs=required,
        )
    ]


def _nih_routes(
    request: str,
    hint: str,
    body: dict[str, Any] | None,
) -> list[RouteCandidate]:
    text = request.lower()
    if not _matches_any(text, ("nih reporter", "reporter", "nih project", "nih grant", "publications")) and hint not in {"nih", "nih_reporter"}:
        return []
    endpoint_id = "publications_search" if "publication" in text else "projects_search"
    required: tuple[str, ...] = ()
    if body is None or "criteria" not in body:
        required = ("body.criteria",)
    return [
        _raw_candidate(
            "nih_reporter",
            endpoint_id,
            get_agency("nih_reporter").endpoints[endpoint_id],
            confidence=0.9 if hint in {"nih", "nih_reporter"} or "nih" in text else 0.76,
            reasons=("NIH RePORTER project/publication terms were detected.",),
            body=body,
            required_inputs=required,
        )
    ]


def _justice_routes(
    request: str,
    hint: str,
    path_params: dict[str, Any],
    query: dict[str, Any],
    limit: int,
) -> list[RouteCandidate]:
    text = request.lower()
    routes: list[RouteCandidate] = []

    routes.extend(_justice_ncvs_routes(request, text, hint, query, limit))
    routes.extend(_justice_crimesolutions_routes(request, text, hint, query))
    routes.extend(_justice_fara_routes(request, text, hint, path_params, query))
    routes.extend(_justice_fbi_routes(request, text, hint, path_params, query))
    return routes


def _justice_ncvs_routes(
    request: str,
    text: str,
    hint: str,
    query: dict[str, Any],
    limit: int,
) -> list[RouteCandidate]:
    ncvs_hint = hint in {"justice_ncvs", "ncvs", "bjs"}
    if not ncvs_hint and not _matches_any(text, ("ncvs", "national crime victimization survey", "victimization survey")):
        return []

    is_household = _matches_any(text, ("household", "households", "property victimization"))
    is_population = _matches_any(text, ("population", "denominator", "weight"))
    if is_household:
        endpoint_id = "household_population" if is_population else "household_victimization"
    else:
        endpoint_id = "personal_population" if is_population else "personal_victimization"

    route_query = {"$limit": query.get("$limit", query.get("limit", limit))}
    year = query.get("year") or _latest_year(request)
    if year:
        route_query["year"] = year
    route_query.update({key: value for key, value in query.items() if key not in {"limit"}})

    return [
        _raw_candidate(
            "justice_ncvs",
            endpoint_id,
            get_agency("justice_ncvs").endpoints[endpoint_id],
            confidence=0.95 if ncvs_hint or "ncvs" in text else 0.86,
            reasons=("NCVS victimization survey terms were detected.",),
            query=route_query,
        )
    ]


def _justice_crimesolutions_routes(
    request: str,
    text: str,
    hint: str,
    query: dict[str, Any],
) -> list[RouteCandidate]:
    cs_hint = hint in {"justice_crimesolutions", "crimesolutions", "crime_solutions"}
    if not cs_hint and not _matches_any(text, ("crimesolutions", "crime solutions", "what works", "rated program", "rated practice")):
        return []

    endpoint_id = "practices" if _matches_any(text, ("practice", "practices")) else "programs"
    route_query = dict(query)
    rating = _crimesolutions_rating(text)
    if rating:
        rating_key = "practice_evidence_rating" if endpoint_id == "practices" else "program_evidence_rating"
        route_query.setdefault(rating_key, rating)

    return [
        _raw_candidate(
            "justice_crimesolutions",
            endpoint_id,
            get_agency("justice_crimesolutions").endpoints[endpoint_id],
            confidence=0.94 if cs_hint or "crimesolutions" in text else 0.84,
            reasons=("CrimeSolutions evidence-rating terms were detected.",),
            query=route_query,
        )
    ]


def _justice_fara_routes(
    request: str,
    text: str,
    hint: str,
    path_params: dict[str, Any],
    query: dict[str, Any],
) -> list[RouteCandidate]:
    fara_hint = hint in {"justice_fara", "fara"}
    if not fara_hint and not _matches_any(text, ("fara", "foreign agents registration act", "foreign agent", "foreign principal", "registrant")):
        return []

    registration_number = str(
        path_params.get("registration_number")
        or query.get("registration_number")
        or _fara_registration_number(request)
        or ""
    )
    is_terminated = _matches_any(text, ("terminated", "inactive", "former"))
    status_endpoint = "terminated" if is_terminated else "active"
    endpoint_id = f"registrants_{status_endpoint}"
    route_query = dict(query)
    route_path_params: dict[str, Any] = {}
    required: tuple[str, ...] = ()

    if _matches_any(text, ("new registrant", "new registration", "registered between", "date range")):
        endpoint_id = "registrants_new"
        start_date, end_date = _fara_date_bounds(request)
        from_date = query.get("from") or start_date
        to_date = query.get("to") or end_date
        if from_date:
            route_query.setdefault("from", from_date)
        if to_date:
            route_query.setdefault("to", to_date)
        required = tuple(name for name in ("from", "to") if not route_query.get(name))
    elif _matches_any(text, ("document", "documents", "filing", "filings")):
        endpoint_id = "registration_documents"
        if registration_number:
            route_path_params["registration_number"] = registration_number
    elif _matches_any(text, ("short form", "short-form", "individual foreign agent")):
        endpoint_id = f"short_forms_{status_endpoint}"
        if registration_number:
            route_path_params["registration_number"] = registration_number
    elif _matches_any(text, ("foreign principal", "foreign principals")):
        endpoint_id = f"foreign_principals_{status_endpoint}"
        if registration_number:
            route_path_params["registration_number"] = registration_number

    route_query.pop("registration_number", None)
    return [
        _raw_candidate(
            "justice_fara",
            endpoint_id,
            get_agency("justice_fara").endpoints[endpoint_id],
            confidence=0.95 if fara_hint or "fara" in text else 0.86,
            reasons=("FARA registrant or foreign-principal terms were detected.",),
            path_params=route_path_params,
            query=route_query,
            required_inputs=required,
        )
    ]


def _justice_fbi_routes(
    request: str,
    text: str,
    hint: str,
    path_params: dict[str, Any],
    query: dict[str, Any],
) -> list[RouteCandidate]:
    fbi_hint = hint in {"justice", "fbi", "cde", "crime-data", "crime_data"}
    if not fbi_hint and not _matches_any(text, ("fbi crime data", "crime data explorer", "ucr", "nibrs", "cde agency")):
        return []

    state_abbr = _state_abbr(request, path_params, query)
    offense = str(path_params.get("offense") or query.get("offense") or _fbi_offense_slug(text) or "violent-crime")
    start_month, end_month = _fbi_month_bounds(request)
    route_query = {
        "from": query.get("from", start_month),
        "to": query.get("to", end_month),
    }
    route_query.update({key: value for key, value in query.items() if key not in {"state", "state_abbr", "offense", "ori"}})

    ori = str(path_params.get("ori") or query.get("ori") or _fbi_ori(request) or "")
    if _matches_any(text, ("agency", "agencies", "ori")):
        if ori and _matches_any(text, ("summary", "summaries", "summarized", "offense")):
            return [
                _raw_candidate(
                    "justice",
                    "summarized_agency",
                    get_agency("justice").endpoints["summarized_agency"],
                    confidence=0.94 if fbi_hint else 0.84,
                    reasons=("FBI CDE agency summary terms and an ORI were detected.",),
                    path_params={"ori": ori, "offense": offense},
                    query=route_query,
                )
            ]
        return [
            _raw_candidate(
                "justice",
                "agencies",
                get_agency("justice").endpoints["agencies"],
                confidence=0.93 if fbi_hint else 0.83,
                reasons=("FBI CDE agency discovery terms were detected.",),
                path_params={"state_abbr": state_abbr} if state_abbr else {},
                query={key: value for key, value in query.items() if key not in {"state", "state_abbr"}},
            )
        ]

    if state_abbr:
        return [
            _raw_candidate(
                "justice",
                "summarized_state",
                get_agency("justice").endpoints["summarized_state"],
                confidence=0.94 if fbi_hint else 0.84,
                reasons=("FBI CDE state summary terms were detected.",),
                path_params={"state_abbr": state_abbr, "offense": offense},
                query=route_query,
            )
        ]

    return [
        _raw_candidate(
            "justice",
            "summarized_national",
            get_agency("justice").endpoints["summarized_national"],
            confidence=0.93 if fbi_hint else 0.82,
            reasons=("FBI CDE national summary terms were detected.",),
            path_params={"offense": offense},
            query=route_query,
        )
    ]


def _raw_candidate(
    agency_id: str,
    endpoint_id: str,
    endpoint: Endpoint,
    *,
    confidence: float,
    reasons: tuple[str, ...],
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    required_inputs: tuple[str, ...] = (),
) -> RouteCandidate:
    clean_path_params = path_params or {}
    clean_query = query or {}
    clean_body = body
    shape_required: tuple[str, ...] = ()
    endpoint_required: tuple[str, ...] = ()
    diagnostics: list[dict[str, Any]] = []
    if endpoint.status != "active":
        note = f": {endpoint.status_note}" if endpoint.status_note else ""
        message = f"Endpoint {agency_id}.{endpoint_id} is {endpoint.status}{note}"
        endpoint_required = (message,)
        diagnostics.append(
            diagnostic(
                "stale_endpoint" if endpoint.status == "stale" else "endpoint_unavailable",
                "warning",
                message,
                route_id=f"{agency_id}.{endpoint_id}",
                endpoint_status=endpoint.status,
                alternatives=list(endpoint.alternatives),
            )
        )
    try:
        normalized = normalize_endpoint_request(
            agency_id,
            endpoint_id,
            path_params=clean_path_params,
            query=clean_query,
            body=clean_body,
        )
        clean_path_params = normalized.path_params
        clean_query = normalized.query
        clean_body = normalized.body
        diagnostics.extend(normalized.diagnostics)
    except RequestShapeError as exc:
        message = str(exc)
        shape_required = (message,)
        diagnostics.append(
            diagnostic(
                "missing_required_input",
                "warning",
                message,
                route_id=f"{agency_id}.{endpoint_id}",
            )
        )

    missing_path = tuple(
        name
        for name in PATH_VAR_RE.findall(endpoint.path)
        if not clean_path_params or clean_path_params.get(name) in {None, ""}
    )
    missing_body = ("body",) if endpoint.method == "POST" and clean_body is None and not required_inputs else ()
    return RouteCandidate(
        route_id=f"{agency_id}.{endpoint_id}",
        action="raw",
        title=f"{get_agency(agency_id).name}: {endpoint.description}",
        confidence=confidence,
        reasons=reasons,
        agency_id=agency_id,
        endpoint_id=endpoint_id,
        path_params=clean_path_params,
        query=clean_query,
        body=clean_body,
        required_inputs=tuple(
            dict.fromkeys(required_inputs + endpoint_required + shape_required + missing_path + missing_body)
        ),
        diagnostics=tuple(diagnostics),
    )


def _dedupe_and_sort(candidates: list[RouteCandidate]) -> list[RouteCandidate]:
    deduped: dict[str, RouteCandidate] = {}
    for candidate in candidates:
        current = deduped.get(candidate.route_id)
        if current is None or candidate.confidence > current.confidence:
            deduped[candidate.route_id] = candidate
    return sorted(deduped.values(), key=lambda candidate: candidate.confidence, reverse=True)


def _planned_status(
    selected: RouteCandidate,
    candidates: list[RouteCandidate],
    *,
    explicit_route: bool,
) -> str:
    competing_complete = [candidate for candidate in candidates[1:] if not candidate.required_inputs]
    if not explicit_route and competing_complete and (
        selected.confidence < 0.8 or selected.confidence - competing_complete[0].confidence < 0.12
    ):
        return "ambiguous"
    if selected.required_inputs:
        return "needs_input"
    if explicit_route:
        return "planned"
    if selected.confidence < 0.8:
        return "ambiguous"
    if competing_complete and selected.confidence - competing_complete[0].confidence < 0.12:
        return "ambiguous"
    return "planned"


def _planning_warnings(
    status: str,
    selected: RouteCandidate,
    candidates: list[RouteCandidate],
) -> list[str]:
    if status == "needs_input":
        if selected.diagnostics and selected.diagnostics[0].get("code") in {"stale_endpoint", "endpoint_unavailable"}:
            return [str(selected.diagnostics[0]["message"])]
        return [f"Missing required inputs: {', '.join(selected.required_inputs)}."]
    if status == "ambiguous":
        return [
            "Multiple GovData routes are plausible; pass route_id or source_hint to choose one.",
            f"Top candidates: {', '.join(candidate.route_id for candidate in candidates[:3])}.",
        ]
    return []


def _default_query_for_request(
    agency_id: str,
    endpoint_id: str,
    request: str,
    limit: int,
) -> dict[str, Any]:
    if agency_id == "datagov" and endpoint_id == "search":
        return {"q": request, "per_page": limit}
    if agency_id == "fred" and endpoint_id == "series_search":
        return {"search_text": request, "limit": limit}
    return {}


def _matches_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _year_bounds(request: str) -> tuple[int | None, int | None]:
    years = [int(value) for value in YEAR_RE.findall(request)]
    if not years:
        return None, None
    return min(years), max(years)


def _latest_year(request: str) -> int | None:
    years = [int(value) for value in YEAR_RE.findall(request)]
    return max(years) if years else None


def _fred_series_id(request: str) -> str | None:
    text = request.lower()
    for term, series_id in FRED_SERIES_ALIASES.items():
        if term in text:
            return series_id
    quoted = re.search(r"\bseries(?:_id| id)?\s*[:=]?\s*([A-Z][A-Z0-9_.-]{1,20})\b", request)
    if quoted:
        return quoted.group(1)
    if "gdp" in text:
        return "GDP"
    return None


def _bls_series_ids(
    request: str,
    query: dict[str, Any],
    body: dict[str, Any] | None,
) -> list[str]:
    if body and isinstance(body.get("seriesid"), list):
        return [str(value) for value in body["seriesid"]]
    if "series_ids" in query and isinstance(query["series_ids"], list):
        return [str(value) for value in query["series_ids"]]
    if "seriesid" in query and isinstance(query["seriesid"], list):
        return [str(value) for value in query["seriesid"]]
    return BLS_SERIES_RE.findall(request)


def _census_dataset(request: str) -> str | None:
    text = request.lower()
    if "acs/acs5" in text or "acs5" in text or "acs 5" in text or "5-year acs" in text:
        return "acs/acs5"
    if "acs/acs1" in text or "acs1" in text or "acs 1" in text or "1-year acs" in text:
        return "acs/acs1"
    return None


def _census_data_query(request: str, query: dict[str, Any]) -> dict[str, Any]:
    route_query = dict(query)
    variables = route_query.pop("variables", None)
    if "get" not in route_query:
        detected_variables = [*CENSUS_VARIABLE_RE.findall(request)]
        if not detected_variables:
            detected_variables = _acs_variable_aliases(request)
        if variables:
            detected_variables = [str(value) for value in variables]
        if detected_variables:
            selected = ["NAME", *[value for value in detected_variables if value != "NAME"]]
            route_query["get"] = ",".join(dict.fromkeys(selected))
    if "for" not in route_query:
        geography = _census_geography(request)
        if geography:
            route_query["for"] = geography
    route_query.pop("year", None)
    route_query.pop("dataset", None)
    route_query.pop("metadata", None)
    return route_query


def _acs_variable_aliases(request: str) -> list[str]:
    text = request.lower()
    return [variable for term, variable in ACS_VARIABLE_ALIASES.items() if term in text]


def _census_geography(request: str) -> str | None:
    text = request.lower()
    if "county" in text:
        return "county:*"
    if "state" in text or "states" in text:
        return "state:*"
    if "us" in text or "united states" in text or "national" in text:
        return "us:*"
    return None


def _search_phrase(request: str, *, remove_terms: tuple[str, ...]) -> str:
    phrase = request
    for term in sorted(remove_terms, key=len, reverse=True):
        phrase = re.sub(re.escape(term), " ", phrase, flags=re.IGNORECASE)
    phrase = re.sub(r"\s+", " ", phrase).strip(" .,:;-")
    phrase = re.sub(r"^(?:for|about|on)\s+", "", phrase, flags=re.IGNORECASE)
    return phrase or request


def _state_abbr(
    request: str,
    path_params: dict[str, Any],
    query: dict[str, Any],
) -> str | None:
    explicit = path_params.get("state_abbr") or path_params.get("state") or query.get("state_abbr") or query.get("state")
    if explicit:
        value = str(explicit).strip().upper()
        if re.fullmatch(r"[A-Z]{2}", value):
            return value

    for name, abbr in STATE_NAME_TO_ABBR.items():
        if re.search(rf"\b{re.escape(name)}\b", request, flags=re.IGNORECASE):
            return abbr

    match = re.search(r"\b(?:state|in|for)\s+([A-Z]{2})\b", request)
    if match:
        return match.group(1)
    return None


def _fbi_offense_slug(text: str) -> str | None:
    for term, slug in FBI_OFFENSE_ALIASES.items():
        if term in text:
            return slug
    return None


def _fbi_month_bounds(request: str) -> tuple[str, str]:
    start, end = _year_bounds(request)
    if start and end:
        return f"01-{start}", f"12-{end}"
    if start:
        return f"01-{start}", f"12-{start}"
    return "01-2020", "12-2020"


def _fbi_ori(request: str) -> str | None:
    match = re.search(r"\b[A-Z]{2}\d{5,7}\b", request)
    return match.group(0) if match else None


def _crimesolutions_rating(text: str) -> str | None:
    if "effective" in text:
        return "Effective"
    if "promising" in text:
        return "Promising"
    if "no effects" in text or "no effect" in text:
        return "No Effects"
    if "inconclusive" in text:
        return "Inconclusive"
    return None


def _fara_registration_number(request: str) -> str | None:
    match = re.search(r"\bregistration(?:\s+number)?\s*[:#]?\s*(\d{3,8})\b", request, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"\bregistrant\s+(\d{3,8})\b", request, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _fara_date_bounds(request: str) -> tuple[str | None, str | None]:
    dates = re.findall(r"\b\d{2}-\d{2}-\d{4}\b", request)
    if len(dates) >= 2:
        return dates[0], dates[1]
    if len(dates) == 1:
        return dates[0], dates[0]

    years = [int(value) for value in YEAR_RE.findall(request)]
    if not years:
        return None, None
    start = min(years)
    end = max(years)
    return f"01-01-{start}", f"12-31-{end}"
