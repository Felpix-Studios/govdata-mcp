from __future__ import annotations

from typing import Any, Literal


Severity = Literal["info", "warning", "error"]


def diagnostic(
    code: str,
    severity: Severity,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    payload.update({key: value for key, value in details.items() if value is not None})
    return payload


def dedupe_diagnostics(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = (
            str(record.get("code") or ""),
            str(record.get("severity") or ""),
            str(record.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def diagnostics_from_warnings(warnings: list[str]) -> list[dict[str, Any]]:
    return dedupe_diagnostics([_diagnostic_from_warning(warning) for warning in warnings])


def _diagnostic_from_warning(warning: str) -> dict[str, Any]:
    code = "warning"
    severity: Severity = "warning"

    if warning.startswith("Missing ") and "endpoint auth" in warning:
        code = "auth_missing"
    elif warning.startswith("Auth key belongs"):
        code = "auth_body_missing"
    elif warning.startswith("Removed unsupported query parameters"):
        code = "request_shape_normalized"
        severity = "info"
    elif warning.startswith("Mapped "):
        code = "request_shape_normalized"
        severity = "info"
    elif warning.startswith("Added Data USA Tesseract"):
        code = "request_shape_normalized"
        severity = "info"
    elif "expected extension" in warning:
        code = "content_type_filename_mismatch"
    elif "rate" in warning.lower() or "throttle" in warning.lower():
        code = "rate_limit_notice"
        severity = "info"
    elif warning.startswith("Upstream request failed with"):
        code = "upstream_request_error"
        severity = "error"

    return diagnostic(code, severity, warning)
