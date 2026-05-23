from __future__ import annotations

import re
import posixpath
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

from .auth_store import auth_readiness_status


IPUMS_API_VERSION = 2
DEFAULT_MAX_TABULAR_BYTES = 250_000_000
MAX_EXCEL_BYTES = 50_000_000
CSV_EXTENSIONS = (".csv.gz", ".csv")
EXCEL_EXTENSIONS = (".xlsx", ".xls")
ZIP_EXTENSIONS = (".zip",)
FIXED_WIDTH_EXTENSIONS = (".dat.gz", ".dat", ".txt.gz", ".txt")
OTHER_DATA_EXTENSIONS = (".dta", ".sav", ".por", ".sas7bdat")
CODEBOOK_EXTENSIONS = (".cbk", ".xml")


@dataclass(frozen=True)
class IpumsCollection:
    id: str
    name: str
    kind: str
    description: str
    download_preference_terms: tuple[str, ...]
    raw_overlap: tuple[str, ...]
    metadata_api: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "download_preference_terms": list(self.download_preference_terms),
            "raw_overlap": list(self.raw_overlap),
            "metadata_api": self.metadata_api,
        }


IPUMS_COLLECTIONS: dict[str, IpumsCollection] = {
    "usa": IpumsCollection(
        id="usa",
        name="IPUMS USA",
        kind="microdata",
        description="Harmonized U.S. decennial census and ACS microdata extracts.",
        download_preference_terms=("acs", "american community survey", "pums", "decennial census", "census microdata"),
        raw_overlap=("census", "datausa"),
    ),
    "cps": IpumsCollection(
        id="cps",
        name="IPUMS CPS",
        kind="microdata",
        description="Harmonized Current Population Survey microdata extracts.",
        download_preference_terms=("cps", "current population survey", "asec"),
        raw_overlap=("bls", "census"),
    ),
    "international": IpumsCollection(
        id="international",
        name="IPUMS International",
        kind="microdata",
        description="Harmonized international census microdata extracts.",
        download_preference_terms=("international census", "global census", "ipums international"),
        raw_overlap=(),
    ),
    "dhs": IpumsCollection(
        id="dhs",
        name="IPUMS DHS",
        kind="microdata",
        description="Harmonized Demographic and Health Surveys extracts.",
        download_preference_terms=("dhs", "demographic and health surveys", "demographic health survey"),
        raw_overlap=(),
    ),
    "atus": IpumsCollection(
        id="atus",
        name="IPUMS ATUS",
        kind="microdata",
        description="Harmonized American Time Use Survey extracts.",
        download_preference_terms=("atus", "american time use survey", "time use"),
        raw_overlap=("bls",),
    ),
    "ahtus": IpumsCollection(
        id="ahtus",
        name="IPUMS AHTUS",
        kind="microdata",
        description="Harmonized American Heritage Time Use Study extracts.",
        download_preference_terms=("ahtus", "american heritage time use study"),
        raw_overlap=(),
    ),
    "mtus": IpumsCollection(
        id="mtus",
        name="IPUMS MTUS",
        kind="microdata",
        description="Harmonized Multinational Time Use Study extracts.",
        download_preference_terms=("mtus", "multinational time use study"),
        raw_overlap=(),
    ),
    "meps": IpumsCollection(
        id="meps",
        name="IPUMS MEPS",
        kind="microdata",
        description="Harmonized Medical Expenditure Panel Survey extracts.",
        download_preference_terms=("meps", "medical expenditure panel survey"),
        raw_overlap=(),
    ),
    "nhis": IpumsCollection(
        id="nhis",
        name="IPUMS NHIS",
        kind="microdata",
        description="Harmonized National Health Interview Survey extracts.",
        download_preference_terms=("nhis", "national health interview survey"),
        raw_overlap=(),
    ),
    "nhgis": IpumsCollection(
        id="nhgis",
        name="IPUMS NHGIS",
        kind="aggregate-spatial",
        description="U.S. aggregate census, ACS, time series, shapefile, and supplemental data extracts.",
        download_preference_terms=("nhgis", "acs summary", "summary file", "census table", "shapefile", "crosswalk"),
        raw_overlap=("census", "datausa"),
        metadata_api=True,
    ),
    "ihgis": IpumsCollection(
        id="ihgis",
        name="IPUMS IHGIS",
        kind="aggregate-spatial",
        description="International aggregate census and GIS extracts.",
        download_preference_terms=("ihgis", "international gis", "international aggregate census"),
        raw_overlap=(),
        metadata_api=True,
    ),
}


MICRODATA_COLLECTION_IDS = tuple(
    collection_id
    for collection_id, collection in IPUMS_COLLECTIONS.items()
    if collection.kind == "microdata"
)
EXTRACT_COLLECTION_IDS = tuple(IPUMS_COLLECTIONS)
METADATA_COLLECTION_IDS = tuple(
    collection_id
    for collection_id, collection in IPUMS_COLLECTIONS.items()
    if collection.metadata_api
)

DOWNLOAD_TERMS = (
    "download",
    "extract",
    "microdata",
    "data file",
    "bulk",
    "csv",
    "fixed width",
    "fixed-width",
    "stata",
    "spss",
    "sas",
    "codebook",
    "shapefile",
)


def normalize_collection(collection: str) -> str:
    normalized = collection.strip().lower().replace("-", "_")
    aliases = {
        "ipums_usa": "usa",
        "ipums_cps": "cps",
        "ipums_international": "international",
        "ipums_dhs": "dhs",
        "ipums_atus": "atus",
        "ipums_ahtus": "ahtus",
        "ipums_mtus": "mtus",
        "ipums_meps": "meps",
        "ipums_nhis": "nhis",
        "ipums_nhgis": "nhgis",
        "ipums_ihgis": "ihgis",
        "american_community_survey": "usa",
        "acs": "usa",
        "census": "usa",
        "decennial": "usa",
        "current_population_survey": "cps",
        "american_time_use_survey": "atus",
        "national_health_interview_survey": "nhis",
        "demographic_and_health_surveys": "dhs",
        "demographic_health_survey": "dhs",
        "medical_expenditure_panel_survey": "meps",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in IPUMS_COLLECTIONS:
        allowed = ", ".join(EXTRACT_COLLECTION_IDS)
        raise ValueError(f"Unsupported IPUMS collection '{collection}'. Supported collections: {allowed}.")
    return normalized


def list_ipums_collections() -> list[dict[str, Any]]:
    return [collection.to_dict() for collection in IPUMS_COLLECTIONS.values()]


def ipums_collection_payload(collection: str | None = None) -> dict[str, Any]:
    if collection:
        collection_id = normalize_collection(collection)
        return {
            "collection": IPUMS_COLLECTIONS[collection_id].to_dict(),
            "extract_api_version": IPUMS_API_VERSION,
            "extract_workflow": {
                "tool": "govdata_get_dataset",
                "actions": {
                    "create": "create_extract",
                    "status": "get_extract",
                    "download": "download_extract",
                    "download_file": "download_file",
                },
            },
        }
    return {
        "collections": list_ipums_collections(),
        "extract_collection_ids": list(EXTRACT_COLLECTION_IDS),
        "microdata_collection_ids": list(MICRODATA_COLLECTION_IDS),
        "metadata_collection_ids": list(METADATA_COLLECTION_IDS),
        "extract_api_version": IPUMS_API_VERSION,
        "notes": [
            "IPUMS extract APIs are asynchronous: create an extract with govdata_get_dataset(action='create_extract'), then call govdata_get_dataset(action='download_extract') with the extract number; it polls until ready and saves selected files.",
            "IPUMS microdata collection metadata is not generally available through the API; use the IPUMS websites for sample IDs and variable mnemonics.",
            "IPUMS NHGIS and IHGIS expose metadata APIs for datasets, tables, shapefiles, and related aggregate/spatial assets.",
        ],
    }


def collection_query(collection: str, *, version: int = IPUMS_API_VERSION) -> dict[str, Any]:
    return {"collection": normalize_collection(collection), "version": version}


def ipums_download_path(download_url_or_path: str) -> str:
    parsed = urlsplit(download_url_or_path)
    path = parsed.path if parsed.scheme or parsed.netloc else download_url_or_path
    marker = "/downloads/"
    if marker in path:
        path = path.split(marker, 1)[1]
    path = path.lstrip("/")
    if path.startswith("downloads/"):
        path = path.removeprefix("downloads/")
    return unquote(path)


def ipums_download_filename(download_url_or_path: str) -> str:
    path = ipums_download_path(download_url_or_path)
    filename = posixpath.basename(path.rstrip("/"))
    if not filename:
        filename = posixpath.basename(urlsplit(download_url_or_path).path.rstrip("/"))
    return unquote(filename)


def ipums_download_links(download_links: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def visit(value: Any, role: str | None = None) -> None:
        if isinstance(value, str):
            add_record(value, role=role)
            return
        if isinstance(value, list):
            for item in value:
                visit(item, role=role)
            return
        if isinstance(value, Mapping):
            url = first_string_value(
                value,
                ("url", "href", "link", "downloadLink", "downloadUrl", "downloadURL"),
            )
            if url:
                add_record(
                    url,
                    role=role
                    or first_string_value(
                        value,
                        ("type", "linkType", "fileType", "label", "name"),
                    ),
                    metadata=value,
                )
                return
            for key, item in value.items():
                visit(item, role=str(key))

    def add_record(
        url: str,
        *,
        role: str | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        path = ipums_download_path(url)
        filename = ipums_download_filename(path)
        records.append(
            {
                "role": role,
                "url": url,
                "download_path": path,
                "filename": filename,
                "file_size": first_int_value(
                    metadata or {},
                    ("fileSize", "file_size", "size", "bytes", "byteCount", "contentLength"),
                ),
            }
        )

    visit(download_links)
    return dedupe_download_records(records)


def select_ipums_downloads(
    extract: Mapping[str, Any],
    *,
    files: str = "data",
    include_codebook: bool = True,
    preferred_formats: list[str] | None = None,
    max_tabular_bytes: int = DEFAULT_MAX_TABULAR_BYTES,
) -> list[dict[str, Any]]:
    mode = files.strip().lower()
    if mode not in {"data", "metadata", "all"}:
        raise ValueError("files must be one of: data, metadata, all")

    records = ipums_download_links(
        extract.get("downloadLinks") or extract.get("downloadLink") or extract.get("links")
    )
    if mode == "all":
        return records

    metadata = [record for record in records if is_ipums_metadata_download(record)]
    if mode == "metadata":
        return metadata

    data_candidates = [record for record in records if not is_ipums_metadata_download(record)]
    selected: list[dict[str, Any]] = []
    if data_candidates:
        selected.append(
            min(
                data_candidates,
                key=lambda record: download_preference_key(
                    record,
                    preferred_formats=preferred_formats,
                    max_tabular_bytes=max_tabular_bytes,
                ),
            )
        )
    if include_codebook:
        selected.extend(metadata)
    return dedupe_download_records(selected)


def is_ipums_metadata_download(record: Mapping[str, Any]) -> bool:
    role = str(record.get("role") or "").lower()
    filename = str(record.get("filename") or "").lower()
    return (
        "codebook" in role
        or "ddi" in role
        or filename.endswith(CODEBOOK_EXTENSIONS)
    )


def download_preference_key(
    record: Mapping[str, Any],
    *,
    preferred_formats: list[str] | None = None,
    max_tabular_bytes: int = DEFAULT_MAX_TABULAR_BYTES,
) -> tuple[int, int, str]:
    filename = str(record.get("filename") or "")
    extension = compound_extension(filename)
    file_size = int_or_none(record.get("file_size"))
    if preferred_formats:
        for index, preferred_format in enumerate(preferred_formats):
            if format_matches_extension(preferred_format, extension):
                return (index, file_size if file_size is not None else 10**18, filename)
        return (len(preferred_formats) + 10, file_size if file_size is not None else 10**18, filename)

    if extension in CSV_EXTENSIONS:
        if file_size is not None and file_size > max_tabular_bytes:
            return (5, file_size, filename)
        return (0, file_size if file_size is not None else 10**18, filename)
    if extension in EXCEL_EXTENSIONS:
        if file_size is not None and file_size > MAX_EXCEL_BYTES:
            return (5, file_size, filename)
        return (1, file_size if file_size is not None else 10**18, filename)
    if extension in ZIP_EXTENSIONS:
        return (2, file_size if file_size is not None else 10**18, filename)
    if extension in OTHER_DATA_EXTENSIONS:
        return (3, file_size if file_size is not None else 10**18, filename)
    if extension in FIXED_WIDTH_EXTENSIONS:
        return (4, file_size if file_size is not None else 10**18, filename)
    return (6, file_size if file_size is not None else 10**18, filename)


def compound_extension(filename: str) -> str:
    lower = filename.lower()
    for extension in (
        *CSV_EXTENSIONS,
        *FIXED_WIDTH_EXTENSIONS,
        *EXCEL_EXTENSIONS,
        *ZIP_EXTENSIONS,
        *OTHER_DATA_EXTENSIONS,
        *CODEBOOK_EXTENSIONS,
    ):
        if lower.endswith(extension):
            return extension
    return posixpath.splitext(lower)[1]


def format_matches_extension(preferred_format: str, extension: str) -> bool:
    normalized = preferred_format.strip().lower().lstrip(".").replace("-", "_")
    aliases = {
        "csv": CSV_EXTENSIONS,
        "csv_gz": (".csv.gz",),
        "excel": EXCEL_EXTENSIONS,
        "xlsx": (".xlsx",),
        "xls": (".xls",),
        "zip": ZIP_EXTENSIONS,
        "stata": (".dta",),
        "dta": (".dta",),
        "fixed_width": FIXED_WIDTH_EXTENSIONS,
        "dat": (".dat.gz", ".dat"),
    }
    return extension in aliases.get(normalized, (f".{normalized}",))


def first_string_value(value: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
    return None


def first_int_value(value: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        parsed = int_or_none(value.get(key))
        if parsed is not None:
            return parsed
    return None


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def dedupe_download_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = str(record.get("download_path") or record.get("url") or record.get("filename"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def detect_ipums_collections(text: str) -> list[str]:
    haystack = f" {text.lower()} "
    matches: list[str] = []
    for collection_id, collection in IPUMS_COLLECTIONS.items():
        terms = (collection_id, collection.name.lower(), *collection.download_preference_terms)
        if any(_contains_term(haystack, term) for term in terms):
            matches.append(collection_id)
    if "acs" in matches and "usa" not in matches:
        matches.append("usa")
    # ACS aggregate/spatial download requests are often better served by NHGIS.
    if any(_contains_term(haystack, term) for term in ("acs", "american community survey", "summary file")):
        if "nhgis" not in matches:
            matches.append("nhgis")
    return list(dict.fromkeys(matches))


def download_intent(text: str) -> bool:
    haystack = text.lower()
    return any(term in haystack for term in DOWNLOAD_TERMS)


def recommend_download_source(request: str, *, prefer_ipums: bool = True) -> dict[str, Any]:
    status = auth_readiness_status(include_endpoints=False)
    auth_kinds = status["auth_kinds"]
    key_status = status["configured_keys"]
    detected = detect_ipums_collections(request)
    is_download = download_intent(request)
    ipums_ready = bool(auth_kinds.get("ipums", {}).get("authenticated", False))
    raw_ready = {
        "census": bool(auth_kinds.get("census", {}).get("authenticated", False)),
        "bls": bool(auth_kinds.get("bls", {}).get("authenticated", False)),
    }

    matched_collections = [IPUMS_COLLECTIONS[collection_id].to_dict() for collection_id in detected]
    overlaps = sorted(
        {
            raw
            for collection_id in detected
            for raw in IPUMS_COLLECTIONS[collection_id].raw_overlap
        }
    )
    both_keys_present = ipums_ready and any(raw_ready.get(raw, False) for raw in overlaps)

    should_prefer_ipums = bool(prefer_ipums and detected and (is_download or both_keys_present) and ipums_ready)
    if should_prefer_ipums:
        recommendation = "ipums_extract"
        reason = (
            "IPUMS_API_KEY is configured and the request looks like a downloadable extract "
            "for an IPUMS-supported collection. Prefer IPUMS over raw Census/BLS endpoints."
        )
    elif detected and not ipums_ready:
        recommendation = "ipums_preferred_but_missing_key"
        reason = "The request matches IPUMS-supported extract collections, but IPUMS_API_KEY is not configured."
    elif detected:
        recommendation = "ipums_available"
        reason = "The request matches IPUMS-supported collections; use IPUMS for extract/download workflows."
    else:
        recommendation = "raw_or_catalog"
        reason = "No IPUMS-supported collection was detected from the request text."

    return {
        "request": request,
        "download_intent": is_download,
        "prefer_ipums": prefer_ipums,
        "recommendation": recommendation,
        "reason": reason,
        "ipums_authenticated": ipums_ready,
        "raw_overlap_authenticated": raw_ready,
        "both_ipums_and_raw_overlap_keys_present": both_keys_present,
        "matched_collections": matched_collections,
        "next_steps": _next_steps(recommendation, detected),
        "auth": {
            "required_for_ipums": ["IPUMS_API_KEY"],
            "ipums_configured": bool(key_status.get("IPUMS_API_KEY", {}).get("configured", False)),
            "setup": "govdata-auth set IPUMS_API_KEY or govdata-auth setup",
        },
    }


def _next_steps(recommendation: str, detected: list[str]) -> list[str]:
    if recommendation == "ipums_extract":
        collection_hint = detected[0] if detected else "cps"
        return [
            f"Use govdata_find_dataset(action='describe', source_hint='ipums', collection='{collection_hint}') to confirm collection scope.",
            f"Build a collection-specific extract JSON payload for collection='{collection_hint}'.",
            f"Submit with govdata_get_dataset(action='create_extract', source='ipums', collection='{collection_hint}', extract={{...}}).",
            f"Call govdata_get_dataset(action='download_extract', source='ipums', collection='{collection_hint}', extract_number=...) with the returned extract number; it polls until ready and saves files to data/govdata-downloads/ipums/.",
        ]
    if recommendation == "ipums_preferred_but_missing_key":
        return [
            "Configure IPUMS_API_KEY with govdata-auth setup or govdata-auth set IPUMS_API_KEY.",
            "If an IPUMS key is unavailable, fall back to the narrowest raw Census/BLS endpoint and state that it is not an IPUMS extract.",
        ]
    if detected:
        return [
            "Use IPUMS when the user wants a downloadable extract or harmonized microdata.",
            "Use raw Census/BLS endpoints only for official API rows, time series, or metadata lookups that are not extract requests.",
        ]
    return [
        "Use govdata_find_dataset(action='search') or govdata_find_dataset(action='metadata') to identify the source.",
    ]


def _contains_term(haystack: str, term: str) -> bool:
    clean = term.strip().lower()
    if not clean:
        return False
    if re.fullmatch(r"[a-z0-9_]+", clean):
        pattern = rf"(?<![a-z0-9]){re.escape(clean)}(?![a-z0-9])"
        return re.search(pattern, haystack) is not None
    return clean in haystack
