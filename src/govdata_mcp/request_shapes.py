from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .diagnostics import diagnostic

USASPENDING_CONTRACT_AWARD_TYPE_CODES = frozenset({"A", "B", "C", "D"})
USASPENDING_ASSISTANCE_AWARD_TYPE_CODES = frozenset({"02", "03", "04", "05"})
USASPENDING_CATEGORY_PATH_SEGMENTS = frozenset(
    {
        "awarding_agency",
        "awarding_subagency",
        "cfda",
        "country",
        "county",
        "defc",
        "district",
        "federal_account",
        "funding_agency",
        "funding_subagency",
        "naics",
        "psc",
        "recipient",
        "recipient_duns",
        "state_territory",
    }
)


class RequestShapeError(ValueError):
    """Raised when endpoint-specific inputs are incomplete or stale."""


@dataclass(frozen=True)
class NormalizedRequest:
    path_params: dict[str, Any]
    query: dict[str, Any]
    body: dict[str, Any] | None
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()


def normalize_endpoint_request(
    agency_id: str,
    endpoint_id: str,
    *,
    path_params: dict[str, Any] | None,
    query: dict[str, Any] | None,
    body: dict[str, Any] | None,
) -> NormalizedRequest:
    clean_path_params = dict(path_params or {})
    clean_query = dict(query or {})
    clean_body = dict(body) if body is not None else None
    warnings: list[str] = []
    diagnostics: list[dict[str, Any]] = []

    if agency_id == "usaspending" and endpoint_id == "search_spending_by_award":
        clean_body = normalize_usaspending_award_body(clean_body, diagnostics)
    elif agency_id == "usaspending" and endpoint_id == "search_spending_by_category":
        clean_path_params, clean_body = normalize_usaspending_category_request(
            clean_path_params,
            clean_body,
            diagnostics,
        )
    elif agency_id == "govinfo" and endpoint_id == "search":
        clean_body = normalize_govinfo_search_body(clean_body)
    elif agency_id == "commerce" and endpoint_id == "image":
        clean_query = normalize_commerce_image_query(clean_query, warnings, diagnostics)
    elif agency_id == "education" and endpoint_id == "schools":
        clean_query = normalize_education_schools_query(clean_query, warnings, diagnostics)
    elif agency_id == "ftc" and endpoint_id == "hsr_early_termination_notices":
        clean_query = remove_unsupported_query_params(
            clean_query,
            unsupported={"limit", "$limit", "offset", "$offset"},
            warnings=warnings,
            endpoint_label="FTC HSR early termination notices",
        )
    elif agency_id == "ftc" and endpoint_id == "dnc_complaints":
        clean_query = normalize_ftc_dnc_query(clean_query, warnings, diagnostics)
    elif agency_id == "nrel" and endpoint_id == "alt_fuel_nearest":
        clean_query = normalize_nrel_nearest_query(clean_query)
    elif agency_id == "justice_crimesolutions" and endpoint_id in {"programs", "practices"}:
        clean_query = remove_unsupported_query_params(
            clean_query,
            unsupported={"limit", "$limit", "offset", "$offset"},
            warnings=warnings,
            endpoint_label="CrimeSolutions CSV feeds",
        )
    elif agency_id == "datausa":
        clean_query = normalize_datausa_query(endpoint_id, clean_query, warnings, diagnostics)
    elif agency_id == "fec" and endpoint_id == "elections":
        clean_query = normalize_fec_elections_query(clean_query)

    return NormalizedRequest(
        path_params=clean_path_params,
        query=clean_query,
        body=clean_body,
        warnings=tuple(warnings),
        diagnostics=tuple(diagnostics),
    )


def normalize_usaspending_category_request(
    path_params: dict[str, Any],
    body: dict[str, Any] | None,
    diagnostics: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if body is None:
        return path_params, body
    raw_category = path_params.get("category") or body.pop("category", None)
    if raw_category is None:
        raise RequestShapeError(
            "USAspending search_spending_by_category requires path_params.category or body.category"
        )
    category = str(raw_category).strip().lower().replace("-", "_").replace(" ", "_")
    if category not in USASPENDING_CATEGORY_PATH_SEGMENTS:
        valid = ", ".join(sorted(USASPENDING_CATEGORY_PATH_SEGMENTS))
        raise RequestShapeError(
            f"USAspending search_spending_by_category category must be one of: {valid}"
        )
    if path_params.get("category") != category:
        path_params["category"] = category
        diagnostics.append(
            diagnostic(
                "request_shape_normalized",
                "info",
                "Mapped USAspending spending_by_category body.category to the provider category path segment.",
                category=category,
            )
        )
    body.setdefault("filters", {})
    return path_params, body


def normalize_usaspending_award_body(
    body: dict[str, Any] | None,
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if body is None:
        return None
    filters = body.setdefault("filters", {})
    if not isinstance(filters, dict):
        return body
    raw_codes = filters.get("award_type_codes") or []
    if isinstance(raw_codes, str):
        codes = {raw_codes}
    else:
        codes = {str(code) for code in raw_codes}
    if not codes:
        return body
    if codes & USASPENDING_CONTRACT_AWARD_TYPE_CODES and codes & USASPENDING_ASSISTANCE_AWARD_TYPE_CODES:
        raise RequestShapeError(
            "USAspending search_spending_by_award award_type_codes cannot mix contract and assistance groups; "
            "use contract codes A,B,C,D or assistance/grant codes 02,03,04,05"
        )
    diagnostics.append(
        diagnostic(
            "request_shape_validated",
            "info",
            "USAspending award_type_codes use one provider-supported award group.",
            award_type_codes=sorted(codes),
        )
    )
    return body


def normalize_commerce_image_query(
    query: dict[str, Any],
    warnings: list[str],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    if "q" in query:
        query.pop("filter[title]", None)
        query.pop("search", None)
        return query
    for legacy_key in ("filter[title]", "search"):
        if legacy_key not in query:
            continue
        value = query.pop(legacy_key)
        query["q"] = value
        message = f"Mapped Commerce image {legacy_key} to provider-supported q search."
        warnings.append(message)
        diagnostics.append(diagnostic("request_shape_normalized", "info", message))
        break
    return query


def normalize_education_schools_query(
    query: dict[str, Any],
    warnings: list[str],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    legacy_bachelors = query.pop("latest.academics.program_available.bachelors", None)
    if legacy_bachelors is not None and "school.degrees_awarded.predominant" not in query:
        if legacy_bachelors in {True, "true", "True", "1", 1}:
            query["school.degrees_awarded.predominant"] = 3
            message = (
                "Mapped legacy Scorecard bachelors-program filter to "
                "school.degrees_awarded.predominant=3."
            )
            warnings.append(message)
            diagnostics.append(diagnostic("request_shape_normalized", "info", message))
    return query


def normalize_govinfo_search_body(body: dict[str, Any] | None) -> dict[str, Any] | None:
    if body is None:
        return None
    body.setdefault("offsetMark", "*")
    body.setdefault("pageSize", 10)
    return body


def remove_unsupported_query_params(
    query: dict[str, Any],
    *,
    unsupported: set[str],
    warnings: list[str],
    endpoint_label: str,
) -> dict[str, Any]:
    removed = [key for key in list(query) if key in unsupported]
    for key in removed:
        query.pop(key, None)
    if removed:
        warnings.append(
            f"Removed unsupported query parameters for {endpoint_label}: {', '.join(sorted(removed))}."
        )
    return query


def normalize_ftc_dnc_query(
    query: dict[str, Any],
    warnings: list[str],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    if "limit" in query and "$limit" not in query:
        value = query.pop("limit")
        query["$limit"] = value
        message = "Mapped FTC DNC limit to Socrata $limit."
        warnings.append(message)
        diagnostics.append(diagnostic("request_shape_normalized", "info", message))
    if "offset" in query and "$offset" not in query:
        value = query.pop("offset")
        query["$offset"] = value
        message = "Mapped FTC DNC offset to Socrata $offset."
        warnings.append(message)
        diagnostics.append(diagnostic("request_shape_normalized", "info", message))
    return query


def normalize_nrel_nearest_query(query: dict[str, Any]) -> dict[str, Any]:
    if "location" not in query:
        return query
    has_coordinates = (
        ("latitude" in query and "longitude" in query)
        or ("lat" in query and ("lon" in query or "lng" in query))
    )
    has_zip = "zip" in query
    if has_coordinates or has_zip:
        query.pop("location", None)
        return query

    zip_match = re.search(r"\b\d{5}(?:-\d{4})?\b", str(query.get("location") or ""))
    if zip_match:
        query["zip"] = zip_match.group(0)
        query.pop("location", None)
        return query

    raise RequestShapeError(
        "NREL alt_fuel_nearest no longer accepts location-only requests; provide latitude/longitude or zip"
    )


def normalize_datausa_query(
    endpoint_id: str,
    query: dict[str, Any],
    warnings: list[str],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    if endpoint_id == "search":
        removed = [key for key in ("q", "kind", "limit") if key in query]
        for key in removed:
            query.pop(key, None)
        if removed:
            warnings.append(
                "Data USA retired the legacy search endpoint; this request now lists Tesseract cubes."
            )
        return query

    if endpoint_id != "data":
        return query

    if "measure" in query and "measures" not in query:
        query["measures"] = query.pop("measure")
    if "Year" in query and "include" not in query:
        query["include"] = f"Year:{query.pop('Year')}"
    if "Geography" in query:
        geography = query.pop("Geography")
        drilldowns = str(query.get("drilldowns") or "")
        if query.get("cube") == "acs_ygso_gender_by_occupation_c_5":
            query.setdefault("State", geography)
        elif "State" in drilldowns and "include" not in query:
            query["include"] = f"State:{geography}"
    if (
        query.get("cube") == "acs_ygso_gender_by_occupation_c_5"
        and "ACS Occupation" in str(query.get("drilldowns") or "")
    ):
        query["drilldowns"] = str(query["drilldowns"]).replace("ACS Occupation", "Occupation")
        message = "Mapped Data USA drilldown 'ACS Occupation' to cube-supported 'Occupation'."
        warnings.append(message)
        diagnostics.append(diagnostic("request_shape_normalized", "info", message))

    if query.get("cube") == "acs_ygso_gender_by_occupation_c_5":
        query = normalize_datausa_occupation_state_filter(query, warnings, diagnostics)

    measures = str(query.get("measures") or "")
    if "cube" not in query and "Population" in measures:
        query["cube"] = "acs_yg_total_population_5"
        message = "Added Data USA Tesseract population cube for a legacy Population request."
        warnings.append(message)
        diagnostics.append(diagnostic("request_shape_normalized", "info", message))
    if "cube" not in query:
        raise RequestShapeError(
            "Data USA Tesseract data requests require query.cube; inspect datausa.search first"
        )
    return query


def normalize_datausa_occupation_state_filter(
    query: dict[str, Any],
    warnings: list[str],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    include = query.get("include")
    if not isinstance(include, str):
        return query

    kept_parts: list[str] = []
    state_value: str | None = None
    for raw_part in include.split(","):
        part = raw_part.strip()
        key, separator, value = part.partition(":")
        if separator and key in {"State", "Geography"}:
            state_value = value
            continue
        if part:
            kept_parts.append(part)

    if state_value and "State" not in query:
        query["State"] = state_value
        message = "Mapped Data USA occupation cube state include filter to provider-supported State parameter."
        warnings.append(message)
        diagnostics.append(diagnostic("request_shape_normalized", "info", message))
    if state_value:
        if kept_parts:
            query["include"] = ",".join(kept_parts)
        else:
            query.pop("include", None)
    return query


def normalize_fec_elections_query(query: dict[str, Any]) -> dict[str, Any]:
    office = str(query.get("office") or "").strip().lower()
    if office == "senate" and not query.get("state"):
        raise RequestShapeError("FEC senate election requests require query.state")
    if office == "house":
        missing = [name for name in ("state", "district") if not query.get(name)]
        if missing:
            required = " and ".join(f"query.{name}" for name in missing)
            raise RequestShapeError(f"FEC house election requests require {required}")
    return query
