from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

from govdata_mcp.client import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    GovDataHTTPClient,
    GovDataError,
    format_path,
    parse_response,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_default_upstream_timeout_is_ten_minutes() -> None:
    assert DEFAULT_HTTP_TIMEOUT_SECONDS == 600


class ChunkedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


def test_format_path_allows_nested_dataset_path() -> None:
    assert (
        format_path("/data/{year}/{dataset}/variables.json", {"year": 2023, "dataset": "acs/acs5"})
        == "/data/2023/acs/acs5/variables.json"
    )


def test_format_path_requires_path_params() -> None:
    try:
        format_path("/packages/{package_id}/summary", {})
    except GovDataError as exc:
        assert "Missing path parameter" in str(exc)
    else:
        raise AssertionError("Expected GovDataError")


def test_census_auth_is_injected_and_redacted(monkeypatch: Any) -> None:
    monkeypatch.setenv("CENSUS_API_KEY", "secret-census-key")

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["key"] == "secret-census-key"
            return httpx.Response(
                200,
                json={"ok": True},
                headers={"content-type": "application/json"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request(
                "census",
                "variables",
                path_params={"year": 2023, "dataset": "acs/acs5"},
            )

    envelope = run(scenario())

    assert envelope["status_code"] == 200
    assert envelope["raw"] == {"ok": True}
    assert envelope["request"]["query"]["key"] == "[REDACTED]"


def test_bls_auth_is_injected_into_body_and_redacted(monkeypatch: Any) -> None:
    monkeypatch.setenv("BLS_API_KEY", "secret-bls-key")

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert payload["registrationkey"] == "secret-bls-key"
            assert payload["seriesid"] == ["CUUR0000SA0"]
            return httpx.Response(
                200,
                json={"status": "REQUEST_SUCCEEDED"},
                headers={"content-type": "application/json"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request(
                "bls",
                "timeseries",
                body={"seriesid": ["CUUR0000SA0"]},
            )

    envelope = run(scenario())

    assert envelope["raw"]["status"] == "REQUEST_SUCCEEDED"
    assert envelope["request"]["body"]["registrationkey"] == "[REDACTED]"


def test_api_data_gov_fallback_key_is_injected_and_redacted(monkeypatch: Any) -> None:
    monkeypatch.setenv("API_DATA_GOV_KEY", "secret-data-gov-key")

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["api_key"] == "secret-data-gov-key"
            return httpx.Response(200, json={"results": []}, headers={"content-type": "application/json"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request("education", "schools", query={"per_page": 1})

    envelope = run(scenario())

    assert envelope["request"]["query"]["api_key"] == "[REDACTED]"
    assert envelope["raw"] == {"results": []}


def test_congress_api_data_gov_key_is_injected_as_redacted_header(monkeypatch: Any) -> None:
    monkeypatch.setenv("API_DATA_GOV_KEY", "secret-data-gov-key")

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url).startswith("https://api.congress.gov/v3/bill")
            assert request.url.params["format"] == "json"
            assert request.url.params["limit"] == "1"
            assert "api_key" not in request.url.params
            assert request.headers["x-api-key"] == "secret-data-gov-key"
            return httpx.Response(200, json={"bills": []}, headers={"content-type": "application/json"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request("loc", "bill", query={"limit": 1})

    envelope = run(scenario())

    assert envelope["request"]["query"]["format"] == "json"
    assert envelope["request"]["headers"]["x-api-key"] == "[REDACTED]"
    assert "api_key" not in envelope["request"]["query"]
    assert envelope["raw"] == {"bills": []}


def test_doj_header_api_data_gov_key_is_injected_and_redacted(monkeypatch: Any) -> None:
    monkeypatch.setenv("API_DATA_GOV_KEY", "secret-data-gov-key")

    seen_paths: list[str] = []

    async def scenario() -> list[dict[str, Any]]:
        def handler(request: httpx.Request) -> httpx.Response:
            seen_paths.append(request.url.path)
            assert "api_key" not in request.url.params
            if not request.url.path.endswith("/api/v1/Registrants/json/Active"):
                assert request.headers["X-Api-Key"] == "secret-data-gov-key"
            else:
                assert "X-Api-Key" not in request.headers
            if request.url.path.endswith("/topics/programs/content"):
                assert "all" in request.url.params
                return httpx.Response(200, text="program_id,title\n1,Example\n", headers={"content-type": "text/csv"})
            return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return [
                await client.request("justice_ncvs", "personal_population", query={"$limit": 1}),
                await client.request("justice_crimesolutions", "programs"),
                await client.request("justice_fara", "registrants_active"),
            ]

    envelopes = run(scenario())

    assert seen_paths == [
        "/bjsdataset/v1/r4j4-fdwx.json",
        "/topics/programs/content",
        "/api/v1/Registrants/json/Active",
    ]
    assert envelopes[0]["request"]["headers"]["X-Api-Key"] == "[REDACTED]"
    assert envelopes[1]["request"]["headers"]["X-Api-Key"] == "[REDACTED]"
    assert envelopes[2]["request"]["headers"] == {}
    assert all("api_key" not in envelope["request"]["query"] for envelope in envelopes)
    assert envelopes[1]["raw"] == "program_id,title\n1,Example\n"
    assert envelopes[2]["classification"] == "PASS"
    assert any(
        record["code"] == "rate_limit_notice" and record["severity"] == "info"
        for record in envelopes[2]["diagnostics"]
    )


def test_fbi_cde_keeps_api_key_query_auth_for_summary(monkeypatch: Any) -> None:
    monkeypatch.setenv("API_DATA_GOV_KEY", "secret-data-gov-key")

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url).startswith("https://api.usa.gov/crime/fbi/cde/summarized/state/CA/violent-crime")
            assert request.url.params["API_KEY"] == "secret-data-gov-key"
            assert request.url.params["from"] == "01-2020"
            assert request.url.params["to"] == "12-2020"
            return httpx.Response(200, json={"results": []}, headers={"content-type": "application/json"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request(
                "justice",
                "summarized_state",
                path_params={"state_abbr": "CA", "offense": "violent-crime"},
                query={"from": "01-2020", "to": "12-2020"},
            )

    envelope = run(scenario())

    assert envelope["request"]["query"]["API_KEY"] == "[REDACTED]"
    assert envelope["raw"] == {"results": []}


def test_fred_defaults_to_json_and_redacts_key(monkeypatch: Any) -> None:
    monkeypatch.setenv("FRED_API_KEY", "secret-fred-key")

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["api_key"] == "secret-fred-key"
            assert request.url.params["file_type"] == "json"
            assert request.url.params["series_id"] == "GDP"
            return httpx.Response(200, json={"seriess": []}, headers={"content-type": "application/json"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request("fred", "series", query={"series_id": "GDP"})

    envelope = run(scenario())

    assert envelope["request"]["query"]["api_key"] == "[REDACTED]"
    assert envelope["request"]["query"]["file_type"] == "json"


def test_encoded_json_response_is_decoded_once(monkeypatch: Any) -> None:
    monkeypatch.setenv("FRED_API_KEY", "secret-fred-key")
    payload = gzip.compress(json.dumps({"observations": [{"date": "2024-01-01"}]}).encode("utf-8"))

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=payload,
                headers={
                    "content-type": "application/json",
                    "content-encoding": "gzip",
                    "content-length": str(len(payload)),
                },
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request("fred", "series_observations", query={"series_id": "GDP"})

    envelope = run(scenario())

    assert envelope["raw"] == {"observations": [{"date": "2024-01-01"}]}


def test_ipums_auth_is_injected_as_authorization_header_and_redacted(monkeypatch: Any) -> None:
    monkeypatch.setenv("IPUMS_API_KEY", "secret-ipums-key")

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "secret-ipums-key"
            assert request.url.params["collection"] == "cps"
            assert request.url.params["version"] == "2"
            return httpx.Response(
                200,
                json={"number": 1, "status": "queued"},
                headers={"content-type": "application/json"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request(
                "ipums",
                "create_extract",
                query={"collection": "cps"},
                body={
                    "description": "test",
                    "dataStructure": {"rectangular": {"on": "P"}},
                    "dataFormat": "fixed_width",
                    "samples": {"cps2019_03s": {}},
                    "variables": {"AGE": {}},
                },
            )

    envelope = run(scenario())

    assert envelope["raw"]["status"] == "queued"
    assert envelope["request"]["headers"]["Authorization"] == "[REDACTED]"
    assert envelope["request"]["query"]["collection"] == "cps"


def test_passthrough_rejects_absolute_url() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: None)) as http:
            client = GovDataHTTPClient(http)
            await client.request_path("fdic", "https://example.com/institutions")

    try:
        run(scenario())
    except GovDataError as exc:
        assert "relative" in str(exc)
    else:
        raise AssertionError("Expected GovDataError")


def test_passthrough_rejects_parent_segments() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: None)) as http:
            client = GovDataHTTPClient(http)
            await client.request_path("fdic", "/institutions/../failures")

    try:
        run(scenario())
    except GovDataError as exc:
        assert "must not contain '..'" in str(exc)
    else:
        raise AssertionError("Expected GovDataError")


def test_passthrough_uses_agency_base_and_default_auth(monkeypatch: Any) -> None:
    monkeypatch.setenv("API_DATA_GOV_KEY", "secret-data-gov-key")

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url).startswith("https://api.open.fec.gov/v1/candidates")
            assert request.url.params["api_key"] == "secret-data-gov-key"
            return httpx.Response(200, json={"api_version": "1.0"}, headers={"content-type": "application/json"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request_path("fec", "/candidates", query={"office": "P"})

    envelope = run(scenario())

    assert envelope["endpoint_id"] == "passthrough"
    assert envelope["request"]["query"]["api_key"] == "[REDACTED]"


def test_unknown_endpoint_fails_before_http() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: None)) as http:
            client = GovDataHTTPClient(http)
            await client.request("datagov", "not_real")

    try:
        run(scenario())
    except KeyError as exc:
        assert "Unknown endpoint_id" in str(exc)
    else:
        raise AssertionError("Expected KeyError")


def test_binary_response_returns_notice_instead_of_text() -> None:
    payload = gzip.compress(b"YEAR,AGE\n2025,40\n")
    response = httpx.Response(
        200,
        content=payload,
        headers={"content-type": "application/gzip"},
        request=httpx.Request("GET", "https://api.ipums.org/downloads/cps/example.csv.gz"),
    )

    raw = parse_response(response)

    assert raw["_govdata_binary_response"] is True
    assert raw["content_type"] == "application/gzip"
    assert "govdata_get_dataset(action='download_file')" in raw["message"]


def test_invalid_json_response_returns_parse_error() -> None:
    response = httpx.Response(
        200,
        content=b"",
        headers={"content-type": "application/json"},
    )

    raw = parse_response(response)

    assert raw["_govdata_parse_error"] == "invalid_json"
    assert raw["body_preview"] == ""


def test_download_file_streams_bytes_and_redacts_auth(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPUMS_API_KEY", "secret-ipums-key")
    payload = gzip.compress(b"YEAR,AGE\n2025,40\n")

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "secret-ipums-key"
            return httpx.Response(
                200,
                content=payload,
                headers={
                    "content-type": "application/gzip",
                    "content-length": str(len(payload)),
                },
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.download_file(
                "ipums",
                "download",
                path_params={"download_path": "cps/api/v1/extracts/1/cps_00001.csv.gz"},
                output_dir="downloads",
            )

    envelope = run(scenario())
    downloaded = Path(envelope["download"]["path"])

    assert downloaded.read_bytes() == payload
    assert envelope["download"]["byte_count"] == len(payload)
    assert envelope["download"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert envelope["request"]["headers"]["Authorization"] == "[REDACTED]"
    assert envelope["download"]["bytes_are_raw"] is True


def test_download_file_rejects_path_traversal_filename(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: None)) as http:
            client = GovDataHTTPClient(http)
            await client.download_file(
                "ipums",
                "download",
                path_params={"download_path": "cps/api/v1/extracts/1/cps_00001.csv.gz"},
                output_dir="downloads",
                filename="../secret.csv.gz",
            )

    try:
        run(scenario())
    except GovDataError as exc:
        assert "simple filename" in str(exc)
    else:
        raise AssertionError("Expected GovDataError")


def test_request_can_save_json_response_to_workspace_data(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CENSUS_API_KEY", "secret-census-key")
    payload = {"variables": {"B01003_001E": {"label": "Total population"}}}

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=payload,
                headers={"content-type": "application/json"},
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request(
                "census",
                "variables",
                path_params={"year": 2023, "dataset": "acs/acs5"},
                save_response=True,
                filename="acs5_variables.json",
            )

    envelope = run(scenario())
    downloaded = Path(envelope["download"]["path"])

    assert downloaded == tmp_path / "data" / "govdata-downloads" / "responses" / "acs5_variables.json"
    assert json.loads(downloaded.read_text(encoding="utf-8")) == payload
    assert envelope["download"]["byte_count"] == len(downloaded.read_bytes())
    assert envelope["download"]["sha256"] == hashlib.sha256(downloaded.read_bytes()).hexdigest()
    assert envelope["raw"]["_govdata_response_saved"] is True
    assert envelope["raw"]["reason"] == "save_to_disk was requested."
    assert envelope["classification"] == "PASS"
    assert any(
        record["code"] == "response_saved" and record["severity"] == "info"
        for record in envelope["diagnostics"]
    )
    assert envelope["saved_artifacts"] == [envelope["download"]]
    assert envelope["agent_next_actions"] == [f"Use the saved file at {envelope['download']['path']}."]


def test_request_warns_when_explicit_filename_extension_mismatches_content(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text="id,title\n1,Example\n",
                headers={"content-type": "text/csv"},
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request(
                "justice_crimesolutions",
                "programs",
                save_response=True,
                filename="programs_sample.json",
            )

    envelope = run(scenario())

    assert any("expected extension '.csv'" in warning for warning in envelope["warnings"])
    assert Path(envelope["download"]["path"]).read_text(encoding="utf-8") == "id,title\n1,Example\n"


def test_large_request_response_auto_saves_instead_of_inlining(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    payload = b'{"variables":{"B01003_001E":{"label":"Total population"}}}'

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=payload,
                headers={
                    "content-type": "application/json",
                    "content-length": str(len(payload)),
                },
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request(
                "census",
                "variables",
                path_params={"year": 2023, "dataset": "acs/acs5"},
                max_inline_bytes=10,
            )

    envelope = run(scenario())
    downloaded = Path(envelope["download"]["path"])

    assert downloaded.is_relative_to(tmp_path / "data")
    assert downloaded.read_bytes() == payload
    assert envelope["raw"]["_govdata_response_saved"] is True
    assert envelope["raw"]["reason"] == "content-length exceeds max_inline_bytes."
    assert "variables" not in envelope["raw"]
    assert envelope["classification"] == "PASS_WITH_WARNING"
    assert envelope["saved_artifacts"] == [envelope["download"]]
    assert any(action.startswith("Read the saved response file") for action in envelope["agent_next_actions"])


def test_streamed_response_auto_save_continues_same_stream(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    payload = b'{"items":[' + b",".join([b'{"id":1}', b'{"id":2}', b'{"id":3}']) + b"]}"
    chunks = [payload[:9], payload[9:22], payload[22:]]

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                stream=ChunkedStream(chunks),
                headers={"content-type": "application/json"},
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request(
                "census",
                "variables",
                path_params={"year": 2023, "dataset": "acs/acs5"},
                max_inline_bytes=10,
            )

    envelope = run(scenario())
    downloaded = Path(envelope["download"]["path"])

    assert downloaded.read_bytes() == payload
    assert envelope["download"]["byte_count"] == len(payload)
    assert envelope["download"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert envelope["download"]["bytes_are_raw"] is False
    assert envelope["raw"]["reason"] == "streamed response exceeded max_inline_bytes."
    assert envelope["classification"] == "PASS_WITH_WARNING"
    assert envelope["saved_artifacts"] == [envelope["download"]]


def test_gzip_stream_auto_save_uses_decoded_size_not_compressed_length(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    decoded_payload = b'{"variables":{"B01003_001E":{"label":"' + (b"Total population " * 400) + b'"}}}'
    compressed_payload = gzip.compress(decoded_payload)
    assert len(compressed_payload) < len(decoded_payload)

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                stream=ChunkedStream([compressed_payload[:13], compressed_payload[13:]]),
                headers={
                    "content-type": "application/json",
                    "content-encoding": "gzip",
                    "content-length": str(len(compressed_payload)),
                },
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request(
                "census",
                "variables",
                path_params={"year": 2023, "dataset": "acs/acs5"},
                max_inline_bytes=len(compressed_payload) + 1,
            )

    envelope = run(scenario())
    downloaded = Path(envelope["download"]["path"])

    assert downloaded.read_bytes() == decoded_payload
    assert envelope["download"]["byte_count"] == len(decoded_payload)
    assert envelope["download"]["content_length"] == len(compressed_payload)
    assert envelope["download"]["content_encoding"] == "gzip"
    assert envelope["download"]["bytes_are_raw"] is False
    assert envelope["raw"]["reason"] == "streamed response exceeded max_inline_bytes."
    assert envelope["classification"] == "PASS_WITH_WARNING"


def test_provider_request_error_returns_source_envelope() -> None:
    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request("justice_fara", "registrants_active")

    envelope = run(scenario())

    assert envelope["status_code"] is None
    assert envelope["source"]["url"].endswith("/api/v1/Registrants/json/Active")
    assert envelope["raw"] == {
        "_govdata_upstream_error": True,
        "error_type": "ConnectError",
        "message": "connection refused",
        "request_url": "https://efile.fara.gov/api/v1/Registrants/json/Active",
    }
    assert any("Upstream request failed with ConnectError" in warning for warning in envelope["warnings"])
    assert envelope["classification"] == "UPSTREAM_ERROR"
    assert any(record["code"] == "upstream_connect_error" for record in envelope["diagnostics"])


def test_provider_request_error_redacts_api_key_from_urls_and_messages(monkeypatch: Any) -> None:
    monkeypatch.setenv("API_DATA_GOV_KEY", "secret-api-data-gov-key")

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout(
                f"timed out requesting {request.url}",
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request(
                "fec",
                "schedule_a",
                query={"two_year_transaction_period": 2024, "per_page": 5},
            )

    envelope = run(scenario())
    serialized = json.dumps(envelope)

    assert envelope["classification"] == "UPSTREAM_ERROR"
    assert "secret-api-data-gov-key" not in serialized
    assert "api_key=[REDACTED]" in serialized
    assert envelope["request"]["query"]["api_key"] == "[REDACTED]"
    assert envelope["raw"]["request_url"].endswith("api_key=[REDACTED]")
    assert any(
        record["code"] == "upstream_request_error" and "api_key=[REDACTED]" in record["source_url"]
        for record in envelope["diagnostics"]
    )


def test_allowlisted_fara_redirect_is_followed_and_saved(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/CallAPI/GetJSON":
                return httpx.Response(
                    200,
                    json={"registrants": [{"name": "Example"}]},
                    headers={"content-type": "application/json"},
                    request=request,
                )
            return httpx.Response(
                302,
                content=b"",
                headers={
                    "location": "https://efile.fara.gov/CallAPI/GetJSON?a=f?p=API:NEWREGISTRANTS_XML",
                },
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request(
                "justice_fara",
                "registrants_new",
                query={"from": "02-01-2024", "to": "02-29-2024"},
                save_response=True,
                output_dir="responses",
                filename="fara_new.json",
            )

    envelope = run(scenario())

    downloaded = Path(envelope["download"]["path"])

    assert envelope["status_code"] == 200
    assert envelope["classification"] == "PASS"
    assert envelope["download"]["byte_count"] == len(downloaded.read_bytes())
    assert json.loads(downloaded.read_text(encoding="utf-8")) == {"registrants": [{"name": "Example"}]}
    assert envelope["source"]["redirects"][0]["location"].startswith("https://efile.fara.gov/CallAPI/")
    assert any(
        record["code"] == "redirect_response" and record["severity"] == "info"
        for record in envelope["diagnostics"]
    )
    assert any(
        record["code"] == "response_saved" and record["severity"] == "info"
        for record in envelope["diagnostics"]
    )
    assert envelope["saved_artifacts"] == [envelope["download"]]


def test_ftc_dnc_limit_is_normalized_and_ignored_provider_limit_is_diagnostic(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("API_DATA_GOV_KEY", "secret-api-data-gov-key")

    async def scenario() -> dict[str, Any]:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["$limit"] == "5"
            assert request.url.params["api_key"] == "secret-api-data-gov-key"
            return httpx.Response(
                200,
                json={"results": [{"id": item} for item in range(50)]},
                request=request,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GovDataHTTPClient(http)
            return await client.request("ftc", "dnc_complaints", query={"limit": 5})

    envelope = run(scenario())

    assert envelope["classification"] == "PASS_WITH_WARNING"
    assert any(record["code"] == "request_shape_normalized" for record in envelope["diagnostics"])
    assert any(record["code"] == "provider_limit_ignored" for record in envelope["diagnostics"])
    assert envelope["requested_limit"] == 5
    assert envelope["record_count"] == 50
    assert envelope["returned_count"] == 50
    assert len(envelope["bounded_preview"]["results"]) == 5
    assert any("bounded_preview" in action for action in envelope["agent_next_actions"])
