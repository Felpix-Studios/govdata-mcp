from __future__ import annotations

import asyncio
from typing import Any

from govdata_mcp.auth_store import PERSISTABLE_ENV_NAMES
from govdata_mcp.ipums import (
    EXTRACT_COLLECTION_IDS,
    METADATA_COLLECTION_IDS,
    detect_ipums_collections,
    ipums_collection_payload,
    recommend_download_source,
    select_ipums_downloads,
)
from govdata_mcp import server as server_module
from govdata_mcp.server import (
    DEFAULT_IPUMS_INITIAL_POLL_SECONDS,
    DEFAULT_IPUMS_INITIAL_POLL_WINDOW_SECONDS,
    DEFAULT_IPUMS_LATE_POLL_SECONDS,
    DEFAULT_IPUMS_MAX_WAIT_SECONDS,
    govdata_find_dataset,
    govdata_get_dataset,
    ipums_poll_schedule,
    ipums_poll_sleep_seconds,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def isolate_auth(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setenv("GOVDATA_AUTH_DISABLE_KEYRING", "1")
    monkeypatch.setenv("GOVDATA_SECRETS_FILE", str(tmp_path / "secrets.env"))
    for name in PERSISTABLE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_ipums_collection_catalog_covers_current_extract_api_collections() -> None:
    assert {
        "usa",
        "cps",
        "international",
        "dhs",
        "atus",
        "ahtus",
        "mtus",
        "meps",
        "nhis",
        "nhgis",
        "ihgis",
    } == set(EXTRACT_COLLECTION_IDS)
    assert {"nhgis", "ihgis"} == set(METADATA_COLLECTION_IDS)

    payload = ipums_collection_payload()
    assert len(payload["collections"]) == len(EXTRACT_COLLECTION_IDS)


def test_ipums_detection_maps_named_surveys_to_collections() -> None:
    assert detect_ipums_collections("Download CPS ASEC microdata") == ["cps"]
    assert "atus" in detect_ipums_collections("I need an ATUS extract")
    assert "nhis" in detect_ipums_collections("Download National Health Interview Survey data")
    assert "dhs" in detect_ipums_collections("DHS survey extract")
    assert {"usa", "nhgis"}.issubset(
        set(detect_ipums_collections("Download ACS PUMS microdata and summary tables"))
    )


def test_download_plan_prefers_ipums_when_overlap_keys_are_present(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    isolate_auth(monkeypatch, tmp_path)
    monkeypatch.setenv("IPUMS_API_KEY", "secret-ipums-key")
    monkeypatch.setenv("CENSUS_API_KEY", "secret-census-key")

    payload = recommend_download_source("Download ACS PUMS microdata for California")

    assert payload["recommendation"] == "ipums_extract"
    assert payload["ipums_authenticated"] is True
    assert payload["both_ipums_and_raw_overlap_keys_present"] is True
    assert "usa" in {collection["id"] for collection in payload["matched_collections"]}
    assert "secret-ipums-key" not in str(payload)


def test_download_plan_reports_missing_ipums_key(monkeypatch: Any, tmp_path: Any) -> None:
    isolate_auth(monkeypatch, tmp_path)
    monkeypatch.setenv("BLS_API_KEY", "secret-bls-key")

    payload = run(govdata_find_dataset(action="plan", request="Download ATUS time use extract"))

    assert payload["recommendation"] == "ipums_preferred_but_missing_key"
    assert payload["ipums_authenticated"] is False
    assert payload["auth"]["setup"] == "govdata-auth set IPUMS_API_KEY or govdata-auth setup"


def test_find_dataset_description_normalizes_ipums_aliases() -> None:
    payload = run(govdata_find_dataset(action="describe", source_hint="ipums", collection="acs"))

    assert payload["result"]["collection"]["id"] == "usa"
    assert payload["result"]["extract_workflow"]["tool"] == "govdata_get_dataset"
    assert payload["result"]["extract_workflow"]["actions"]["create"] == "create_extract"


def test_find_dataset_metadata_reports_microdata_collection_error() -> None:
    payload = run(govdata_find_dataset(action="metadata", source_hint="ipums", collection="cps"))

    assert payload["status"] == "error"
    assert "metadata API is available" in payload["warnings"][0]


def test_get_dataset_create_extract_uses_ipums_endpoint(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_request_raw(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append({"args": args, "kwargs": kwargs})
        return {"raw": {"number": 1, "status": "queued"}}

    monkeypatch.setattr(server_module, "request_raw", fake_request_raw)

    payload = run(
        govdata_get_dataset(
            action="create_extract",
            source="ipums",
            collection="cps",
            extract={
                "description": "test",
                "dataStructure": {"rectangular": {"on": "P"}},
                "dataFormat": "csv",
                "samples": {"cps2019_03s": {}},
                "variables": {"AGE": {}},
            },
        )
    )

    assert payload["raw"]["status"] == "queued"
    assert calls[0]["args"][:2] == ("ipums", "create_extract")
    assert calls[0]["kwargs"]["query"]["collection"] == "cps"


def test_get_dataset_get_extract_uses_ipums_endpoint(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_request_raw(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append({"args": args, "kwargs": kwargs})
        return {"raw": {"number": 1, "status": "completed"}}

    monkeypatch.setattr(server_module, "request_raw", fake_request_raw)

    payload = run(
        govdata_get_dataset(
            action="get_extract",
            source="ipums",
            collection="cps",
            extract_number=1,
        )
    )

    assert payload["raw"]["status"] == "completed"
    assert calls[0]["args"][:2] == ("ipums", "extract")
    assert calls[0]["kwargs"]["path_params"] == {"extract_number": 1}


def test_ipums_download_selection_prefers_csv_and_codebook() -> None:
    extract = {
        "downloadLinks": {
            "data": {
                "url": "https://api.ipums.org/downloads/cps/api/v1/extracts/1/cps_00001.csv.gz",
                "fileSize": 120_000,
            },
            "zip": {
                "url": "https://api.ipums.org/downloads/cps/api/v1/extracts/1/cps_00001_csv.zip",
                "fileSize": 90_000,
            },
            "codebook": "https://api.ipums.org/downloads/cps/api/v1/extracts/1/cps_00001.cbk",
        }
    }

    selected = select_ipums_downloads(extract)

    assert [record["filename"] for record in selected] == ["cps_00001.csv.gz", "cps_00001.cbk"]


def test_ipums_download_selection_uses_zip_for_large_tabular_file() -> None:
    extract = {
        "downloadLinks": {
            "data": {
                "url": "https://api.ipums.org/downloads/cps/api/v1/extracts/1/cps_00001.csv.gz",
                "fileSize": 300_000_001,
            },
            "zip": {
                "url": "https://api.ipums.org/downloads/cps/api/v1/extracts/1/cps_00001_csv.zip",
                "fileSize": 150_000_000,
            },
        }
    }

    selected = select_ipums_downloads(extract, include_codebook=False)

    assert [record["filename"] for record in selected] == ["cps_00001_csv.zip"]


def test_ipums_download_selection_uses_small_excel_when_no_csv() -> None:
    extract = {
        "downloadLinks": {
            "excel": {
                "url": "https://api.ipums.org/downloads/nhgis/api/v1/extracts/1/nhgis0001.xlsx",
                "fileSize": 10_000,
            },
            "zip": {
                "url": "https://api.ipums.org/downloads/nhgis/api/v1/extracts/1/nhgis0001_csv.zip",
                "fileSize": 8_000,
            },
        }
    }

    selected = select_ipums_downloads(extract, include_codebook=False)

    assert [record["filename"] for record in selected] == ["nhgis0001.xlsx"]


def test_ipums_default_poll_schedule_is_adaptive() -> None:
    assert DEFAULT_IPUMS_MAX_WAIT_SECONDS == 1800
    assert ipums_poll_schedule() == {
        "initial_poll_seconds": DEFAULT_IPUMS_INITIAL_POLL_SECONDS,
        "initial_window_seconds": DEFAULT_IPUMS_INITIAL_POLL_WINDOW_SECONDS,
        "late_poll_seconds": DEFAULT_IPUMS_LATE_POLL_SECONDS,
    }
    assert ipums_poll_sleep_seconds(elapsed=0, max_wait=1800, poll_interval_seconds=None) == 60
    assert ipums_poll_sleep_seconds(elapsed=599, max_wait=1800, poll_interval_seconds=None) == 60
    assert ipums_poll_sleep_seconds(elapsed=600, max_wait=1800, poll_interval_seconds=None) == 300
    assert ipums_poll_sleep_seconds(elapsed=1700, max_wait=1800, poll_interval_seconds=None) == 100
    assert ipums_poll_sleep_seconds(elapsed=0, max_wait=1800, poll_interval_seconds=0) == 0
    assert ipums_poll_sleep_seconds(elapsed=0, max_wait=1800, poll_interval_seconds=15) == 15


def test_ipums_download_extract_saves_selected_files(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_request_raw(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "raw": {
                "status": "completed",
                "downloadLinks": {
                    "data": "https://api.ipums.org/downloads/cps/api/v1/extracts/1/cps_00001.csv.gz",
                    "codebook": "https://api.ipums.org/downloads/cps/api/v1/extracts/1/cps_00001.cbk",
                },
            }
        }

    async def fake_download_file(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append({"args": args, "kwargs": kwargs})
        return {"download": {"saved": True, "path": kwargs["filename"]}}

    monkeypatch.setattr(server_module, "request_raw", fake_request_raw)
    monkeypatch.setattr(server_module, "download_file", fake_download_file)

    payload = run(
        govdata_get_dataset(
            action="download_extract",
            source="ipums",
            collection="cps",
            extract_number=1,
        )
    )

    assert payload["status"] == "completed"
    assert payload["ready"] is True
    assert payload["poll"]["attempts"] == 1
    assert [call["kwargs"]["filename"] for call in calls] == ["cps_00001.csv.gz", "cps_00001.cbk"]
    assert all(call["kwargs"]["output_dir"].endswith("ipums/cps/extract_1") for call in calls)


def test_ipums_download_extract_polls_until_ready_before_download(monkeypatch: Any) -> None:
    statuses = iter(
        [
            {"status": "queued"},
            {"status": "started"},
            {
                "status": "completed",
                "downloadLinks": {
                    "data": "https://api.ipums.org/downloads/cps/api/v1/extracts/1/cps_00001.csv.gz",
                },
            },
        ]
    )
    downloads: list[dict[str, Any]] = []

    async def fake_request_raw(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"raw": next(statuses), "retrieved_at": "2026-05-18T00:00:00Z", "status_code": 200}

    async def fake_download_file(*args: Any, **kwargs: Any) -> dict[str, Any]:
        downloads.append({"args": args, "kwargs": kwargs})
        return {"download": {"saved": True, "path": kwargs["filename"]}}

    monkeypatch.setattr(server_module, "request_raw", fake_request_raw)
    monkeypatch.setattr(server_module, "download_file", fake_download_file)

    payload = run(
        govdata_get_dataset(
            action="download_extract",
            source="ipums",
            collection="cps",
            extract_number=1,
            poll_interval_seconds=0,
            max_wait_seconds=30,
        )
    )

    assert payload["ready"] is True
    assert payload["status"] == "completed"
    assert payload["poll"]["attempts"] == 3
    assert [record["status"] for record in payload["poll"]["history"]] == [
        "queued",
        "started",
        "completed",
    ]
    assert [call["kwargs"]["filename"] for call in downloads] == ["cps_00001.csv.gz"]


def test_ipums_download_extract_returns_pending_after_timeout(monkeypatch: Any) -> None:
    async def fake_request_raw(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "raw": {"status": "queued"},
            "retrieved_at": "2026-05-18T00:00:00Z",
            "status_code": 200,
        }

    async def fake_download_file(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("download_file should not run before the extract is ready")

    monkeypatch.setattr(server_module, "request_raw", fake_request_raw)
    monkeypatch.setattr(server_module, "download_file", fake_download_file)

    payload = run(
        govdata_get_dataset(
            action="download_extract",
            source="ipums",
            collection="cps",
            extract_number=1,
            poll_interval_seconds=0,
            max_wait_seconds=0,
        )
    )

    assert payload["ready"] is False
    assert payload["timed_out"] is True
    assert payload["status"] == "queued"
    assert payload["downloads"] == []
    assert payload["poll"]["attempts"] == 1
    assert "continue polling" in payload["warnings"][1]
    assert "govdata_get_dataset" in payload["warnings"][1]


def test_ipums_download_extract_stops_on_terminal_failure(monkeypatch: Any) -> None:
    async def fake_request_raw(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "raw": {"status": "failed"},
            "retrieved_at": "2026-05-18T00:00:00Z",
            "status_code": 200,
        }

    monkeypatch.setattr(server_module, "request_raw", fake_request_raw)

    payload = run(
        govdata_get_dataset(
            action="download_extract",
            source="ipums",
            collection="cps",
            extract_number=1,
        )
    )

    assert payload["ready"] is False
    assert payload["status"] == "failed"
    assert payload["downloads"] == []
    assert payload["poll"]["attempts"] == 1
    assert "terminal status" in payload["warnings"][0]
