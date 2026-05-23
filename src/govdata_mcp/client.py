from __future__ import annotations

import asyncio
import hashlib
import json
import os
import posixpath
import re
import time
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, unquote_plus, urljoin, urlsplit, urlunsplit

import httpx

from .auth_store import load_persisted_auth
from .diagnostics import dedupe_diagnostics, diagnostic, diagnostics_from_warnings
from .registry import AUTH_ENV, Agency, Endpoint, Method, get_agency, get_endpoint
from .request_shapes import normalize_endpoint_request


SENSITIVE_KEYS = {
    "api_key",
    "key",
    "registrationkey",
    "x-api-key",
    "authorization",
    "token",
    "access_token",
}
SENSITIVE_QUERY_KEY_RE = re.compile(
    r"(?i)([?&](?:api_key|key|registrationkey|x-api-key|authorization|token|access_token)=)([^&#\s]+)"
)
TRUTHY = {"1", "true", "yes", "y", "on"}
PATH_VAR_RE = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)}")
BINARY_CONTENT_MARKERS = (
    "application/gzip",
    "application/x-gzip",
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
    "application/x-stata",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument",
)
BINARY_EXTENSIONS = (
    ".csv.gz",
    ".dat.gz",
    ".txt.gz",
    ".zip",
    ".gz",
    ".dta",
    ".sav",
    ".por",
    ".sas7bdat",
    ".xlsx",
    ".xls",
)
DEFAULT_MAX_INLINE_BYTES = 5_000_000
DEFAULT_HTTP_TIMEOUT_SECONDS = 600
RESPONSE_DOWNLOAD_DIR = "data/govdata-downloads/responses"
DECODED_BODY_HEADER_DROP = {"content-encoding", "content-length", "transfer-encoding"}


class GovDataError(Exception):
    """Raised for invalid MCP request arguments."""


class RateGate:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_call: dict[str, float] = {}

    async def wait(self, agency: Agency) -> None:
        if agency.min_seconds_between_requests <= 0:
            return
        lock = self._locks.setdefault(agency.id, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            elapsed = now - self._last_call.get(agency.id, 0)
            delay = agency.min_seconds_between_requests - elapsed
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_call[agency.id] = time.monotonic()


RATE_GATE = RateGate()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def redact_text(value: str) -> str:
    return SENSITIVE_QUERY_KEY_RE.sub(r"\1[REDACTED]", value)


def redact_url(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return redact_text(value)
    if not parts.query:
        return redact_text(value)

    changed = False
    query_parts: list[str] = []
    for part in parts.query.split("&"):
        if not part:
            query_parts.append(part)
            continue
        key, separator, _current_value = part.partition("=")
        if unquote_plus(key).lower() in SENSITIVE_KEYS:
            changed = True
            query_parts.append(f"{key}{separator or '='}[REDACTED]")
        else:
            query_parts.append(part)

    if not changed:
        return redact_text(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(query_parts), parts.fragment))


def normalize_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    return dict(value)


def format_path(path_template: str, path_params: Mapping[str, Any] | None) -> str:
    params = normalize_mapping(path_params)

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            raise GovDataError(f"Missing path parameter '{name}' for {path_template}")
        return quote(str(params[name]), safe="/")

    return PATH_VAR_RE.sub(replace, path_template)


def response_content_length(response: httpx.Response) -> int | None:
    value = response.headers.get("content-length")
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def is_binary_response_metadata(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    if any(marker in content_type for marker in BINARY_CONTENT_MARKERS):
        return True
    disposition = response.headers.get("content-disposition", "").lower()
    url_path = ""
    try:
        url_path = urlsplit(str(response.url)).path.lower()
    except RuntimeError:
        pass
    if any(url_path.endswith(extension) for extension in BINARY_EXTENSIONS):
        return True
    return "attachment" in disposition and any(
        extension in disposition for extension in BINARY_EXTENSIONS
    )


def is_binary_response(response: httpx.Response) -> bool:
    content = response.content
    if not content:
        return False

    if is_binary_response_metadata(response):
        return True
    content_type = response.headers.get("content-type", "").lower()
    if (
        content_type.startswith("text/")
        or "json" in content_type
        or "xml" in content_type
        or "csv" in content_type
    ):
        return False

    sample = content[:2048]
    if b"\x00" in sample:
        return True
    try:
        sample.decode(response.encoding or "utf-8")
    except UnicodeDecodeError:
        return True
    return False


def parse_response(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type.lower():
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            return {
                "_govdata_parse_error": "invalid_json",
                "message": str(exc),
                "content_type": content_type,
                "content_length": response_content_length(response),
                "body_preview": response.text[:500] if response.content else "",
            }
    if is_binary_response(response):
        return {
            "_govdata_binary_response": True,
            "content_type": content_type or None,
            "content_length": response_content_length(response),
            "message": (
                "Binary response omitted from raw output. Use an MCP download "
                "tool such as govdata_get_dataset(action='download_file') or "
                "govdata_get_dataset(action='download_extract') to "
                "save bytes to disk."
            ),
        }
    text = response.text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def decoded_body_headers(headers: httpx.Headers | Mapping[str, str]) -> dict[str, str]:
    """Return headers that are safe for reparsing an already-decoded body."""
    return {
        key: value
        for key, value in dict(headers).items()
        if key.lower() not in DECODED_BODY_HEADER_DROP
    }


def parse_decoded_response(
    *,
    status_code: int,
    headers: httpx.Headers,
    content: bytes,
    request: httpx.Request,
) -> Any:
    return parse_response(
        httpx.Response(
            status_code,
            headers=decoded_body_headers(headers),
            content=content,
            request=request,
        )
    )


def env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUTHY


def find_auth_key(endpoint: Endpoint) -> tuple[str | None, str | None]:
    load_persisted_auth()
    env_names = AUTH_ENV[endpoint.auth]
    for env_name in env_names:
        if os.getenv(env_name):
            return os.getenv(env_name), env_name
    if endpoint.demo_key and env_truthy("GOVDATA_ALLOW_DEMO_KEY"):
        return endpoint.demo_key, "GOVDATA_ALLOW_DEMO_KEY"
    return None, " or ".join(env_names) if env_names else None


def apply_auth(
    endpoint: Endpoint,
    query: dict[str, Any],
    body: dict[str, Any] | None,
    headers: dict[str, str],
    warnings: list[str],
) -> None:
    if endpoint.auth == "none":
        return

    key, env_name = find_auth_key(endpoint)
    if not key:
        warnings.append(
            f"Missing {env_name} for endpoint auth '{endpoint.auth}'. "
            "The upstream API may reject this request."
        )
        return

    auth_name = endpoint.auth_name or "api_key"
    if endpoint.auth_location == "query":
        query.setdefault(auth_name, key)
    elif endpoint.auth_location == "body":
        if body is None:
            warnings.append("Auth key belongs in request body, but no JSON body was provided.")
        else:
            body.setdefault(auth_name, key)
    elif endpoint.auth_location == "header":
        headers.setdefault(auth_name, key)


def normalize_passthrough_path(agency: Agency, path: str, method: Method) -> str:
    if method not in agency.passthrough_methods:
        allowed = ", ".join(agency.passthrough_methods)
        raise GovDataError(f"Method '{method}' is not allowed for '{agency.id}'. Allowed: {allowed}.")

    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc:
        raise GovDataError("Passthrough path must be relative to the configured agency base URL.")
    if parsed.query or parsed.fragment:
        raise GovDataError("Put query parameters in the query argument, not in the passthrough path.")
    if path.startswith("//"):
        raise GovDataError("Protocol-relative passthrough paths are not allowed.")

    decoded = unquote(path)
    if "\\" in decoded or "\x00" in decoded:
        raise GovDataError("Passthrough path contains unsupported characters.")
    if not decoded.startswith("/"):
        raise GovDataError("Passthrough path must start with '/'.")
    if any(segment == ".." for segment in decoded.split("/")):
        raise GovDataError("Passthrough path must not contain '..' segments.")

    normalized = posixpath.normpath(decoded)
    if normalized == ".":
        normalized = "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if decoded.endswith("/") and not normalized.endswith("/"):
        normalized = f"{normalized}/"

    allowed = False
    for prefix in agency.passthrough_prefixes:
        clean_prefix = prefix if prefix.startswith("/") else f"/{prefix}"
        clean_prefix = clean_prefix.rstrip("/") or "/"
        if clean_prefix == "/" or normalized == clean_prefix or normalized.startswith(f"{clean_prefix}/"):
            allowed = True
            break
    if not allowed:
        raise GovDataError(
            f"Path '{normalized}' is outside allowed prefixes for '{agency.id}': "
            f"{', '.join(agency.passthrough_prefixes)}"
        )

    return normalized


def passthrough_endpoint(agency: Agency, path: str, method: Method) -> Endpoint:
    return Endpoint(
        id="passthrough",
        method=method,
        path=path,
        description=f"Safe passthrough request to {agency.name}.",
        docs_url=agency.docs_url,
        auth=agency.default_auth,
        auth_location=agency.default_auth_location,
        auth_name=agency.default_auth_name,
        demo_key=agency.default_demo_key,
    )


def default_filename_from_path(path: str) -> str:
    parsed = urlsplit(path)
    basename = posixpath.basename(parsed.path.rstrip("/"))
    filename = unquote(basename)
    if not filename:
        raise GovDataError(f"Could not infer filename from download path '{path}'.")
    return validate_download_filename(filename)


def validate_download_filename(filename: str) -> str:
    if not filename or filename in {".", ".."}:
        raise GovDataError("Download filename must not be empty.")
    if "/" in filename or "\\" in filename or "\x00" in filename:
        raise GovDataError("Download filename must be a simple filename, not a path.")
    return filename


def safe_filename_part(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "_", text)
    text = text.strip("._-")
    return text[:80] or "response"


def response_extension(content_type: str | None, path: str) -> str:
    lowered_type = (content_type or "").lower()
    lowered_path = urlsplit(path).path.lower()
    for extension in BINARY_EXTENSIONS:
        if lowered_path.endswith(extension):
            return extension
    if "json" in lowered_type:
        return ".json"
    if "csv" in lowered_type:
        return ".csv"
    if "xml" in lowered_type:
        return ".xml"
    if "html" in lowered_type:
        return ".html"
    if lowered_type.startswith("text/"):
        return ".txt"
    return ".bin"


def filename_content_warning(filename: str | None, content_type: str | None, path: str) -> str | None:
    if not filename:
        return None
    expected_extension = response_extension(content_type, path)
    if expected_extension == ".bin":
        return None
    if filename.lower().endswith(expected_extension):
        return None
    return (
        f"Requested filename '{filename}' does not match response content type "
        f"{content_type or 'unknown'}; expected extension '{expected_extension}'."
    )


def default_response_filename(
    agency_id: str,
    endpoint_id: str,
    path: str,
    content_type: str | None,
) -> str:
    timestamp = now_iso().replace("-", "").replace(":", "").replace("Z", "Z")
    stem = "_".join(
        safe_filename_part(part)
        for part in (agency_id, endpoint_id)
        if str(part).strip()
    )
    return validate_download_filename(
        f"{stem}_{timestamp}{response_extension(content_type, path)}"
    )


def resolve_download_target(output_dir: str | os.PathLike[str] | None, filename: str) -> Path:
    workspace = Path.cwd().resolve()
    base = Path(output_dir).expanduser() if output_dir else workspace / "data" / "govdata-downloads"
    if not base.is_absolute():
        base = workspace / base
    base = base.resolve(strict=False)
    try:
        base.relative_to(workspace)
    except ValueError as exc:
        raise GovDataError(
            f"Download output_dir '{base}' is outside the workspace '{workspace}'."
        ) from exc

    target = (base / validate_download_filename(filename)).resolve(strict=False)
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise GovDataError(f"Download target '{target}' escapes output_dir '{base}'.") from exc
    return target


def resolve_response_target(
    output_dir: str | os.PathLike[str] | None,
    filename: str | None,
    *,
    agency_id: str,
    endpoint_id: str,
    path: str,
    content_type: str | None,
) -> Path:
    response_filename = filename or default_response_filename(
        agency_id,
        endpoint_id,
        path,
        content_type,
    )
    return resolve_download_target(output_dir or RESPONSE_DOWNLOAD_DIR, response_filename)


def configured_max_inline_bytes(max_inline_bytes: int | None) -> int:
    if max_inline_bytes is not None:
        return max(0, int(max_inline_bytes))
    value = os.getenv("GOVDATA_MAX_INLINE_BYTES")
    if value:
        try:
            return max(0, int(value))
        except ValueError:
            pass
    return DEFAULT_MAX_INLINE_BYTES


def saved_response_notice(
    *,
    reason: str,
    content_type: str | None,
    content_length: int | None,
    max_inline_bytes: int,
) -> dict[str, Any]:
    return {
        "_govdata_response_saved": True,
        "reason": reason,
        "content_type": content_type,
        "content_length": content_length,
        "max_inline_bytes": max_inline_bytes,
        "message": (
            "Response body was saved to disk instead of returned through MCP. "
            "Read the path in the download metadata from the project workspace."
        ),
    }


async def iter_response_chunks(
    response: httpx.Response,
    *,
    raw_bytes: bool,
) -> AsyncIterator[bytes]:
    stream = response.aiter_raw() if raw_bytes else response.aiter_bytes()
    try:
        async for chunk in stream:
            yield chunk
    except httpx.StreamConsumed as exc:
        try:
            content = response.content
        except httpx.ResponseNotRead as content_exc:
            raise GovDataError(
                "Response stream was already consumed before GovData could read or save it."
            ) from content_exc
        if content:
            yield content


async def stream_response_to_disk(
    response: httpx.Response,
    target: Path,
    *,
    initial_chunks: list[bytes] | None = None,
    remaining_chunks: AsyncIterator[bytes] | None = None,
    raw_bytes: bool = False,
) -> dict[str, Any]:
    temp_target = target.with_name(f".{target.name}.part")
    target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    sha256 = hashlib.sha256()
    byte_count = 0
    completed = False
    try:
        with temp_target.open("wb") as handle:
            for chunk in initial_chunks or []:
                if not chunk:
                    continue
                handle.write(chunk)
                sha256.update(chunk)
                byte_count += len(chunk)
            stream = remaining_chunks or iter_response_chunks(response, raw_bytes=raw_bytes)
            async for chunk in stream:
                if not chunk:
                    continue
                handle.write(chunk)
                sha256.update(chunk)
                byte_count += len(chunk)
        os.replace(temp_target, target)
        completed = True
    finally:
        if not completed and temp_target.exists():
            try:
                temp_target.unlink()
            except OSError:
                pass

    return {
        "saved": True,
        "path": str(target),
        "filename": target.name,
        "byte_count": byte_count,
        "sha256": sha256.hexdigest(),
        "content_type": response.headers.get("content-type") or None,
        "content_length": response_content_length(response),
        "content_encoding": response.headers.get("content-encoding") or None,
        "bytes_are_raw": raw_bytes,
    }


async def read_inline_or_save_response(
    response: httpx.Response,
    *,
    save_response: bool,
    output_dir: str | os.PathLike[str] | None,
    filename: str | None,
    agency_id: str,
    endpoint_id: str,
    path: str,
    max_inline_bytes: int | None,
) -> tuple[bytes | None, dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    limit = configured_max_inline_bytes(max_inline_bytes)
    content_type = response.headers.get("content-type") or None
    content_length = response_content_length(response)
    target = resolve_response_target(
        output_dir,
        filename,
        agency_id=agency_id,
        endpoint_id=endpoint_id,
        path=path,
        content_type=content_type,
    )
    warnings = [
        warning
        for warning in [filename_content_warning(filename, content_type, path)]
        if warning
    ]
    if save_response:
        download = await stream_response_to_disk(response, target)
        return None, download, saved_response_notice(
            reason="save_to_disk was requested.",
            content_type=content_type,
            content_length=content_length,
            max_inline_bytes=limit,
        ), warnings
    if is_binary_response_metadata(response):
        download = await stream_response_to_disk(response, target, raw_bytes=True)
        return None, download, saved_response_notice(
            reason="response appears to be a binary or attachment payload.",
            content_type=content_type,
            content_length=content_length,
            max_inline_bytes=limit,
        ), warnings
    if content_length is not None and content_length > limit:
        download = await stream_response_to_disk(response, target)
        return None, download, saved_response_notice(
            reason="content-length exceeds max_inline_bytes.",
            content_type=content_type,
            content_length=content_length,
            max_inline_bytes=limit,
        ), warnings

    chunks: list[bytes] = []
    byte_count = 0
    stream = iter_response_chunks(response, raw_bytes=False)
    async for chunk in stream:
        if not chunk:
            continue
        chunks.append(chunk)
        byte_count += len(chunk)
        if byte_count > limit:
            download = await stream_response_to_disk(
                response,
                target,
                initial_chunks=chunks,
                remaining_chunks=stream,
            )
            return None, download, saved_response_notice(
                reason="streamed response exceeded max_inline_bytes.",
                content_type=content_type,
                content_length=content_length,
                max_inline_bytes=limit,
            ), warnings
    return b"".join(chunks), None, None, warnings


def redirect_source_metadata(
    response: httpx.Response,
    prior_redirects: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    redirects = list(prior_redirects or [])
    redirects.extend(
        [
            {
                "status_code": redirect.status_code,
                "url": redact_url(str(redirect.url)),
                "location": redact_url(redirect.headers.get("location")),
            }
            for redirect in response.history
        ]
    )
    location = response.headers.get("location")
    if location:
        redirects.append(
            {
                "status_code": response.status_code,
                "url": redact_url(str(response.url)),
                "location": redact_url(location),
            }
        )
    if not redirects:
        return None
    return {"redirects": redirects}


def allowlisted_endpoint_redirect_url(
    agency: Agency,
    endpoint: Endpoint,
    response: httpx.Response,
) -> str | None:
    if endpoint.redirect_policy != "preserve_same_host_redirect_metadata":
        return None
    if response.status_code < 300 or response.status_code >= 400:
        return None
    location = response.headers.get("location")
    if not location:
        return None
    target = urljoin(str(response.url), location)
    source_parts = urlsplit(str(response.url))
    target_parts = urlsplit(target)
    if (source_parts.scheme, source_parts.netloc) != (target_parts.scheme, target_parts.netloc):
        return None
    if agency.id == "justice_fara" and endpoint.id == "registrants_new" and target_parts.path == "/CallAPI/GetJSON":
        return target
    return None


def redirect_record(response: httpx.Response, target_url: str) -> dict[str, Any]:
    return {
        "status_code": response.status_code,
        "url": redact_url(str(response.url)),
        "location": redact_url(target_url),
    }


def saved_artifacts_from_download(download: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(download, dict) or not download.get("saved"):
        return []
    return [download]


def bounded_preview_from_raw(raw: Any, limit: int | None) -> Any:
    if limit is None or limit < 0:
        return None
    if isinstance(raw, list):
        return raw[:limit]
    if isinstance(raw, dict):
        for key in ("results", "data", "rows"):
            value = raw.get(key)
            if isinstance(value, list):
                preview = dict(raw)
                preview[key] = value[:limit]
                return preview
    return None


def agent_next_actions(
    diagnostics: list[dict[str, Any]],
    *,
    download: dict[str, Any] | None,
    bounded_preview: Any,
) -> list[str]:
    actions: list[str] = []
    codes = {str(record.get("code") or "") for record in diagnostics}
    if "response_saved" in codes and download and download.get("path"):
        actions.append(f"Use the saved file at {download['path']}.")
    if "response_auto_saved" in codes and download and download.get("path"):
        actions.append(f"Read the saved response file at {download['path']} before summarizing the data.")
    if "empty_result" in codes:
        actions.append("Treat the empty HTTP 200 as a valid provider response; broaden or revise filters if rows are needed.")
    if "provider_limit_ignored" in codes and bounded_preview is not None:
        actions.append("Use bounded_preview for the requested row count, or explicitly page/filter the provider response.")
    if "redirect_empty_body" in codes:
        actions.append("Use the preserved redirect metadata to retry later or inspect the provider redirect target.")
    if "upstream_connect_error" in codes:
        actions.append("Retry later with backoff; the provider connection failed before a response body was available.")
    return actions


def add_agent_fields(
    envelope: dict[str, Any],
    *,
    query: Mapping[str, Any],
    raw: Any,
    download: dict[str, Any] | None,
    diagnostics: list[dict[str, Any]],
) -> None:
    limit = requested_limit(query)
    count = response_record_count(raw)
    if count is not None:
        envelope["record_count"] = count
        envelope["returned_count"] = count
    if limit is not None:
        envelope["requested_limit"] = limit
    if count is not None and limit is not None and count > limit:
        preview = bounded_preview_from_raw(raw, limit)
        if preview is not None:
            envelope["bounded_preview"] = preview
    else:
        preview = None
    artifacts = saved_artifacts_from_download(download)
    if artifacts:
        envelope["saved_artifacts"] = artifacts
    actions = agent_next_actions(diagnostics, download=download, bounded_preview=preview)
    if actions:
        envelope["agent_next_actions"] = actions


def response_classification(
    status_code: int | None,
    _warnings: list[str],
    diagnostics: list[dict[str, Any]],
) -> str:
    if status_code is None or status_code >= 400:
        return "UPSTREAM_ERROR"
    if 300 <= status_code < 400:
        return "PASS_WITH_WARNING"
    if any(record.get("severity") in {"warning", "error"} for record in diagnostics):
        return "PASS_WITH_WARNING"
    return "PASS"


def requested_limit(query: Mapping[str, Any]) -> int | None:
    for key in ("$limit", "limit"):
        if key not in query:
            continue
        try:
            return int(str(query[key]).split(",", 1)[0])
        except (TypeError, ValueError):
            return None
    return None


def response_record_count(raw: Any) -> int | None:
    if isinstance(raw, list):
        return len(raw)
    if not isinstance(raw, dict):
        return None
    for key in ("results", "data", "rows"):
        value = raw.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def has_empty_result(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    metadata = raw.get("metadata")
    if isinstance(metadata, dict) and metadata.get("total") == 0:
        return True
    if raw.get("total") == 0 and any(raw.get(key) == [] for key in ("results", "data", "rows")):
        return True
    return False


def response_diagnostics(
    *,
    agency: Agency,
    endpoint: Endpoint,
    response: httpx.Response,
    query: Mapping[str, Any],
    warnings: list[str],
    base_diagnostics: list[dict[str, Any]],
    raw: Any,
    download: dict[str, Any] | None,
    prior_redirects: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    records = [*base_diagnostics, *diagnostics_from_warnings(warnings)]
    if isinstance(raw, dict) and raw.get("_govdata_response_saved"):
        explicit_save = raw.get("reason") == "save_to_disk was requested."
        code = "response_saved" if explicit_save else "response_auto_saved"
        severity = "info" if explicit_save else "warning"
        records.append(
            diagnostic(
                code,
                severity,
                str(raw.get("reason") or "Response body was saved to disk instead of returned through MCP."),
                download_path=(download or {}).get("path"),
                content_type=raw.get("content_type"),
                content_length=raw.get("content_length"),
                max_inline_bytes=raw.get("max_inline_bytes"),
            )
        )

    redirect_metadata = redirect_source_metadata(response, prior_redirects)
    if redirect_metadata:
        empty_saved_redirect = bool(download and download.get("byte_count") == 0)
        empty_inline_redirect = raw in ("", b"", None) or (isinstance(raw, dict) and not raw)
        code = "redirect_empty_body" if empty_saved_redirect or empty_inline_redirect else "redirect_response"
        severity = "warning" if code == "redirect_empty_body" else "info"
        records.append(
            diagnostic(
                code,
                severity,
                "Provider returned a redirect; redirect metadata was preserved in the source envelope.",
                redirects=redirect_metadata["redirects"],
            )
        )

    if 200 <= response.status_code < 300 and has_empty_result(raw):
        records.append(
            diagnostic(
                "empty_result",
                "warning",
                "Provider returned status 200 with zero records.",
            )
        )

    if agency.id == "ftc" and endpoint.id == "dnc_complaints":
        limit = requested_limit(query)
        count = response_record_count(raw)
        if limit is not None and count is not None and count > limit:
            records.append(
                diagnostic(
                    "provider_limit_ignored",
                    "warning",
                    "Provider returned more records than requested by the bounded limit.",
                    requested_limit=limit,
                    returned_records=count,
                )
            )

    return dedupe_diagnostics(records)


def upstream_request_error_envelope(
    *,
    agency: Agency,
    endpoint: Endpoint,
    method: Method,
    url: str,
    path: str,
    path_params: Mapping[str, Any],
    query: Mapping[str, Any],
    body: Mapping[str, Any] | None,
    headers: Mapping[str, str],
    warnings: list[str],
    error: httpx.RequestError,
    download: dict[str, Any] | None = None,
    prior_redirects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    message = redact_text(str(error) or error.__class__.__name__)
    request = getattr(error, "request", None)
    upstream_url = redact_url(str(request.url)) if request is not None else redact_url(url)
    source_url = redact_url(url)
    warning = f"Upstream request failed with {error.__class__.__name__}: {message}"
    error_code = "upstream_connect_error" if isinstance(error, httpx.ConnectError) else "upstream_request_error"
    diagnostics = dedupe_diagnostics(
        [
            *diagnostics_from_warnings(warnings),
            diagnostic(
                error_code,
                "error",
                warning,
                error_type=error.__class__.__name__,
                source_url=upstream_url,
                retryable=True,
            ),
        ]
    )
    envelope = {
        "agency_id": agency.id,
        "agency_name": agency.name,
        "endpoint_id": endpoint.id,
        "status_code": None,
        "retrieved_at": now_iso(),
        "source": {
            "base_url": agency.base_url,
            "url": source_url,
            "agency_docs_url": agency.docs_url,
            "endpoint_docs_url": endpoint.docs_url,
            **({"redirects": prior_redirects} if prior_redirects else {}),
        },
        "request": {
            "method": method,
            "path": path,
            "path_params": redact(path_params),
            "query": redact(query),
            "body": redact(body),
            "headers": redact(headers),
        },
        "warnings": [*warnings, warning],
        "diagnostics": diagnostics,
        "classification": "UPSTREAM_ERROR",
        "raw": {
            "_govdata_upstream_error": True,
            "error_type": error.__class__.__name__,
            "message": message,
            "request_url": upstream_url,
        },
        **({"download": download} if download is not None else {}),
    }
    add_agent_fields(envelope, query=query, raw=envelope["raw"], download=download, diagnostics=diagnostics)
    return envelope


class GovDataHTTPClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "GovDataHTTPClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def request(
        self,
        agency_id: str,
        endpoint_id: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        save_response: bool = False,
        output_dir: str | os.PathLike[str] | None = None,
        filename: str | None = None,
        max_inline_bytes: int | None = None,
    ) -> dict[str, Any]:
        agency = get_agency(agency_id)
        endpoint = get_endpoint(agency, endpoint_id)
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
            self._owns_client = True

        request_query = dict(endpoint.default_query)
        request_query.update(normalize_mapping(query))
        request_body = normalize_mapping(body) if body is not None else None
        normalized = normalize_endpoint_request(
            agency.id,
            endpoint.id,
            path_params=normalize_mapping(path_params),
            query=request_query,
            body=request_body,
        )
        request_path_params = normalized.path_params
        request_query = normalized.query
        request_body = normalized.body
        headers: dict[str, str] = {}
        warnings: list[str] = list(normalized.warnings)
        base_diagnostics: list[dict[str, Any]] = list(normalized.diagnostics)

        apply_auth(endpoint, request_query, request_body, headers, warnings)

        path = format_path(endpoint.path, request_path_params)
        url = f"{agency.base_url.rstrip('/')}{path}"
        prior_redirects: list[dict[str, Any]] = []

        async def read_response(response: httpx.Response) -> tuple[Any, dict[str, Any] | None]:
            content, download, raw_notice, response_warnings = await read_inline_or_save_response(
                response,
                save_response=save_response,
                output_dir=output_dir,
                filename=filename,
                agency_id=agency.id,
                endpoint_id=endpoint.id,
                path=path,
                max_inline_bytes=max_inline_bytes,
            )
            warnings.extend(response_warnings)
            if content is None:
                return raw_notice, download
            return (
                parse_decoded_response(
                    status_code=response.status_code,
                    headers=response.headers,
                    content=content,
                    request=response.request,
                ),
                download,
            )

        await RATE_GATE.wait(agency)
        try:
            async with self._client.stream(
                endpoint.method,
                url,
                params=request_query or None,
                json=request_body if endpoint.method != "GET" else None,
                headers=headers or None,
            ) as response:
                redirect_url = allowlisted_endpoint_redirect_url(agency, endpoint, response)
                if redirect_url:
                    prior_redirects.append(redirect_record(response, redirect_url))
                    await response.aread()
                    async with self._client.stream("GET", redirect_url, headers=headers or None) as redirected:
                        response = redirected
                        raw, download = await read_response(response)
                else:
                    raw, download = await read_response(response)
        except httpx.RequestError as exc:
            if agency.rate_limit_note:
                warnings.append(agency.rate_limit_note)
            if endpoint.rate_limit_note:
                warnings.append(endpoint.rate_limit_note)
            return upstream_request_error_envelope(
                agency=agency,
                endpoint=endpoint,
                method=endpoint.method,
                url=url,
                path=path,
                path_params=request_path_params,
                query=request_query,
                body=request_body,
                headers=headers,
                warnings=warnings,
                error=exc,
                prior_redirects=prior_redirects,
            )
        if agency.rate_limit_note:
            warnings.append(agency.rate_limit_note)
        if endpoint.rate_limit_note:
            warnings.append(endpoint.rate_limit_note)

        diagnostics = response_diagnostics(
            agency=agency,
            endpoint=endpoint,
            response=response,
            query=request_query,
            warnings=warnings,
            base_diagnostics=base_diagnostics,
            raw=raw,
            download=download,
            prior_redirects=prior_redirects,
        )
        envelope = {
            "agency_id": agency.id,
            "agency_name": agency.name,
            "endpoint_id": endpoint.id,
            "status_code": response.status_code,
            "retrieved_at": now_iso(),
            "source": {
                "base_url": agency.base_url,
                "url": url,
                "agency_docs_url": agency.docs_url,
                "endpoint_docs_url": endpoint.docs_url,
                **(redirect_source_metadata(response, prior_redirects) or {}),
            },
            "request": {
                "method": endpoint.method,
                "path": path,
                "path_params": redact(request_path_params),
                "query": redact(request_query),
                "body": redact(request_body),
                "headers": redact(headers),
            },
            "warnings": warnings,
            "diagnostics": diagnostics,
            "classification": response_classification(response.status_code, warnings, diagnostics),
            "raw": raw,
        }
        if download is not None:
            envelope["download"] = download
        add_agent_fields(envelope, query=request_query, raw=raw, download=download, diagnostics=diagnostics)
        return envelope

    async def request_path(
        self,
        agency_id: str,
        path: str,
        *,
        method: Method = "GET",
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        save_response: bool = False,
        output_dir: str | os.PathLike[str] | None = None,
        filename: str | None = None,
        max_inline_bytes: int | None = None,
    ) -> dict[str, Any]:
        agency = get_agency(agency_id)
        if agency.status != "active":
            raise KeyError(f"Agency '{agency.id}' is planned but not implemented.")
        normalized_path = normalize_passthrough_path(agency, path, method)
        endpoint = passthrough_endpoint(agency, normalized_path, method)
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
            self._owns_client = True

        request_query = normalize_mapping(query)
        request_body = normalize_mapping(body) if body is not None else None
        normalized = normalize_endpoint_request(
            agency.id,
            endpoint.id,
            path_params={},
            query=request_query,
            body=request_body,
        )
        request_query = normalized.query
        request_body = normalized.body
        headers: dict[str, str] = {}
        warnings: list[str] = list(normalized.warnings)
        base_diagnostics: list[dict[str, Any]] = list(normalized.diagnostics)

        apply_auth(endpoint, request_query, request_body, headers, warnings)

        url = f"{agency.base_url.rstrip('/')}{normalized_path}"
        await RATE_GATE.wait(agency)
        try:
            async with self._client.stream(
                method,
                url,
                params=request_query or None,
                json=request_body if method != "GET" else None,
                headers=headers or None,
            ) as response:
                content, download, raw_notice, response_warnings = await read_inline_or_save_response(
                    response,
                    save_response=save_response,
                    output_dir=output_dir,
                    filename=filename,
                    agency_id=agency.id,
                    endpoint_id=endpoint.id,
                    path=normalized_path,
                    max_inline_bytes=max_inline_bytes,
                )
                warnings.extend(response_warnings)

                if content is None:
                    raw = raw_notice
                else:
                    raw = parse_decoded_response(
                        status_code=response.status_code,
                        headers=response.headers,
                        content=content,
                        request=response.request,
                    )
        except httpx.RequestError as exc:
            if agency.rate_limit_note:
                warnings.append(agency.rate_limit_note)
            return upstream_request_error_envelope(
                agency=agency,
                endpoint=endpoint,
                method=method,
                url=url,
                path=normalized_path,
                path_params={},
                query=request_query,
                body=request_body,
                headers=headers,
                warnings=warnings,
                error=exc,
            )
        if agency.rate_limit_note:
            warnings.append(agency.rate_limit_note)

        diagnostics = response_diagnostics(
            agency=agency,
            endpoint=endpoint,
            response=response,
            query=request_query,
            warnings=warnings,
            base_diagnostics=base_diagnostics,
            raw=raw,
            download=download,
        )
        envelope = {
            "agency_id": agency.id,
            "agency_name": agency.name,
            "endpoint_id": endpoint.id,
            "status_code": response.status_code,
            "retrieved_at": now_iso(),
            "source": {
                "base_url": agency.base_url,
                "url": url,
                "agency_docs_url": agency.docs_url,
                "endpoint_docs_url": agency.docs_url,
                **(redirect_source_metadata(response) or {}),
            },
            "request": {
                "method": method,
                "path": normalized_path,
                "path_params": {},
                "query": redact(request_query),
                "body": redact(request_body),
                "headers": redact(headers),
            },
            "warnings": warnings,
            "diagnostics": diagnostics,
            "classification": response_classification(response.status_code, warnings, diagnostics),
            "raw": raw,
        }
        if download is not None:
            envelope["download"] = download
        add_agent_fields(envelope, query=request_query, raw=raw, download=download, diagnostics=diagnostics)
        return envelope

    async def download_file(
        self,
        agency_id: str,
        endpoint_id: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        output_dir: str | os.PathLike[str] | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        agency = get_agency(agency_id)
        endpoint = get_endpoint(agency, endpoint_id)
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
            self._owns_client = True

        request_query = dict(endpoint.default_query)
        request_query.update(normalize_mapping(query))
        request_body = normalize_mapping(body) if body is not None else None
        normalized = normalize_endpoint_request(
            agency.id,
            endpoint.id,
            path_params=normalize_mapping(path_params),
            query=request_query,
            body=request_body,
        )
        request_path_params = normalized.path_params
        request_query = normalized.query
        request_body = normalized.body
        headers: dict[str, str] = {}
        warnings: list[str] = list(normalized.warnings)
        base_diagnostics: list[dict[str, Any]] = list(normalized.diagnostics)

        apply_auth(endpoint, request_query, request_body, headers, warnings)

        path = format_path(endpoint.path, request_path_params)
        url = f"{agency.base_url.rstrip('/')}{path}"
        target = resolve_download_target(output_dir, filename or default_filename_from_path(path))
        temp_target = target.with_name(f".{target.name}.part")

        await RATE_GATE.wait(agency)
        try:
            async with self._client.stream(
                endpoint.method,
                url,
                params=request_query or None,
                json=request_body if endpoint.method != "GET" else None,
                headers=headers or None,
            ) as response:
                if agency.rate_limit_note:
                    warnings.append(agency.rate_limit_note)
                if endpoint.rate_limit_note:
                    warnings.append(endpoint.rate_limit_note)

                if response.status_code < 200 or response.status_code >= 300:
                    content = await response.aread()
                    raw = parse_decoded_response(
                        status_code=response.status_code,
                        headers=response.headers,
                        content=content,
                        request=response.request,
                    )
                    download = {
                        "saved": False,
                        "path": str(target),
                    }
                    diagnostics = response_diagnostics(
                        agency=agency,
                        endpoint=endpoint,
                        response=response,
                        query=request_query,
                        warnings=warnings,
                        base_diagnostics=base_diagnostics,
                        raw=raw,
                        download=download,
                    )
                    envelope = {
                        "agency_id": agency.id,
                        "agency_name": agency.name,
                        "endpoint_id": endpoint.id,
                        "status_code": response.status_code,
                        "retrieved_at": now_iso(),
                        "source": {
                            "base_url": agency.base_url,
                            "url": url,
                            "agency_docs_url": agency.docs_url,
                            "endpoint_docs_url": endpoint.docs_url,
                            **(redirect_source_metadata(response) or {}),
                        },
                        "request": {
                            "method": endpoint.method,
                            "path": path,
                            "path_params": redact(request_path_params),
                            "query": redact(request_query),
                            "body": redact(request_body),
                            "headers": redact(headers),
                        },
                        "warnings": warnings,
                        "diagnostics": diagnostics,
                        "classification": response_classification(response.status_code, warnings, diagnostics),
                        "download": download,
                        "raw": raw,
                    }
                    add_agent_fields(envelope, query=request_query, raw=raw, download=download, diagnostics=diagnostics)
                    return envelope

                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                sha256 = hashlib.sha256()
                byte_count = 0
                completed = False
                try:
                    with temp_target.open("wb") as handle:
                        async for chunk in iter_response_chunks(response, raw_bytes=True):
                            if not chunk:
                                continue
                            handle.write(chunk)
                            sha256.update(chunk)
                            byte_count += len(chunk)
                    os.replace(temp_target, target)
                    completed = True
                finally:
                    if not completed and temp_target.exists():
                        try:
                            temp_target.unlink()
                        except OSError:
                            pass

                download = {
                    "saved": True,
                    "path": str(target),
                    "filename": target.name,
                    "byte_count": byte_count,
                    "sha256": sha256.hexdigest(),
                    "content_type": response.headers.get("content-type") or None,
                    "content_length": response_content_length(response),
                    "content_encoding": response.headers.get("content-encoding") or None,
                    "bytes_are_raw": True,
                }
                diagnostics = response_diagnostics(
                    agency=agency,
                    endpoint=endpoint,
                    response=response,
                    query=request_query,
                    warnings=warnings,
                    base_diagnostics=base_diagnostics,
                    raw=None,
                    download=download,
                )
                envelope = {
                    "agency_id": agency.id,
                    "agency_name": agency.name,
                    "endpoint_id": endpoint.id,
                    "status_code": response.status_code,
                    "retrieved_at": now_iso(),
                    "source": {
                        "base_url": agency.base_url,
                        "url": url,
                        "agency_docs_url": agency.docs_url,
                        "endpoint_docs_url": endpoint.docs_url,
                        **(redirect_source_metadata(response) or {}),
                    },
                    "request": {
                        "method": endpoint.method,
                        "path": path,
                        "path_params": redact(request_path_params),
                        "query": redact(request_query),
                        "body": redact(request_body),
                        "headers": redact(headers),
                    },
                    "warnings": warnings,
                    "diagnostics": diagnostics,
                    "classification": response_classification(response.status_code, warnings, diagnostics),
                    "download": download,
                }
                add_agent_fields(envelope, query=request_query, raw=None, download=download, diagnostics=diagnostics)
                return envelope
        except httpx.RequestError as exc:
            if agency.rate_limit_note and agency.rate_limit_note not in warnings:
                warnings.append(agency.rate_limit_note)
            if endpoint.rate_limit_note and endpoint.rate_limit_note not in warnings:
                warnings.append(endpoint.rate_limit_note)
            return upstream_request_error_envelope(
                agency=agency,
                endpoint=endpoint,
                method=endpoint.method,
                url=url,
                path=path,
                path_params=request_path_params,
                query=request_query,
                body=request_body,
                headers=headers,
                warnings=warnings,
                error=exc,
                download={"saved": False, "path": str(target)},
            )


async def request_raw(
    agency_id: str,
    endpoint_id: str,
    *,
    path_params: Mapping[str, Any] | None = None,
    query: Mapping[str, Any] | None = None,
    body: Mapping[str, Any] | None = None,
    save_response: bool = False,
    output_dir: str | os.PathLike[str] | None = None,
    filename: str | None = None,
    max_inline_bytes: int | None = None,
) -> dict[str, Any]:
    async with GovDataHTTPClient() as client:
        return await client.request(
            agency_id,
            endpoint_id,
            path_params=path_params,
            query=query,
            body=body,
            save_response=save_response,
            output_dir=output_dir,
            filename=filename,
            max_inline_bytes=max_inline_bytes,
        )


async def request_agency_path(
    agency_id: str,
    path: str,
    *,
    method: Method = "GET",
    query: Mapping[str, Any] | None = None,
    body: Mapping[str, Any] | None = None,
    save_response: bool = False,
    output_dir: str | os.PathLike[str] | None = None,
    filename: str | None = None,
    max_inline_bytes: int | None = None,
) -> dict[str, Any]:
    async with GovDataHTTPClient() as client:
        return await client.request_path(
            agency_id,
            path,
            method=method,
            query=query,
            body=body,
            save_response=save_response,
            output_dir=output_dir,
            filename=filename,
            max_inline_bytes=max_inline_bytes,
        )


async def download_file(
    agency_id: str,
    endpoint_id: str,
    *,
    path_params: Mapping[str, Any] | None = None,
    query: Mapping[str, Any] | None = None,
    body: Mapping[str, Any] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    async with GovDataHTTPClient() as client:
        return await client.download_file(
            agency_id,
            endpoint_id,
            path_params=path_params,
            query=query,
            body=body,
            output_dir=output_dir,
            filename=filename,
        )
