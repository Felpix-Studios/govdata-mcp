from __future__ import annotations

import json
import os
from typing import Any

from govdata_mcp.auth_store import (
    PERSISTABLE_ENV_NAMES,
    auth_readiness_status,
    delete_persisted_secret,
    load_persisted_auth,
    read_file_secrets,
    save_persisted_secret,
    secret_sources,
    secrets_file_path,
)


def isolate_auth(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setenv("GOVDATA_AUTH_DISABLE_KEYRING", "1")
    monkeypatch.setenv("GOVDATA_SECRETS_FILE", str(tmp_path / "secrets.env"))
    for name in PERSISTABLE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_file_secret_is_loaded_for_mcp_auth(monkeypatch: Any, tmp_path: Any) -> None:
    isolate_auth(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"

    store = save_persisted_secret("FRED_API_KEY", "persisted-fred-key", preferred_store="file")
    assert store == "file"

    load_persisted_auth(force=True)

    assert secrets_file_path() == secrets_path
    assert read_file_secrets()["FRED_API_KEY"] == "persisted-fred-key"
    assert os.getenv("FRED_API_KEY") == "persisted-fred-key"
    assert secret_sources("FRED_API_KEY") == ["environment", "file"]


def test_environment_overrides_persisted_file_secret(monkeypatch: Any, tmp_path: Any) -> None:
    isolate_auth(monkeypatch, tmp_path)
    monkeypatch.setenv("API_DATA_GOV_KEY", "env-data-gov-key")

    save_persisted_secret("API_DATA_GOV_KEY", "file-data-gov-key", preferred_store="file")
    load_persisted_auth(force=True)

    assert read_file_secrets()["API_DATA_GOV_KEY"] == "file-data-gov-key"
    assert os.getenv("API_DATA_GOV_KEY") == "env-data-gov-key"
    assert secret_sources("API_DATA_GOV_KEY") == ["environment", "file"]


def test_delete_persisted_file_secret(monkeypatch: Any, tmp_path: Any) -> None:
    isolate_auth(monkeypatch, tmp_path)

    save_persisted_secret("CENSUS_API_KEY", "persisted-census-key", preferred_store="file")
    removed = delete_persisted_secret("CENSUS_API_KEY")

    assert removed == ["file"]
    assert "CENSUS_API_KEY" not in read_file_secrets()


def test_auth_store_rejects_unsupported_names() -> None:
    assert "FRED_API_KEY" in PERSISTABLE_ENV_NAMES

    try:
        save_persisted_secret("NOT_A_GOVDATA_KEY", "value", preferred_store="file")
    except ValueError as exc:
        assert "Unsupported GovData auth name" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_auth_readiness_reports_missing_keys_without_values(monkeypatch: Any, tmp_path: Any) -> None:
    isolate_auth(monkeypatch, tmp_path)

    status = auth_readiness_status()

    assert status["configured_keys"]["FRED_API_KEY"]["configured"] is False
    assert status["auth_kinds"]["fred"]["authenticated"] is False
    assert status["auth_kinds"]["fred"]["missing_env"] == ["FRED_API_KEY"]
    assert status["auth_kinds"]["noaa_token"]["endpoint_backed"] is False
    assert status["auth_kinds"]["noaa_token"]["endpoint_count"] == 0
    assert "none" not in status["auth_kinds"]
    json.dumps(status)


def test_auth_readiness_detects_file_backed_keys_without_leaking_values(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    isolate_auth(monkeypatch, tmp_path)

    save_persisted_secret("FRED_API_KEY", "persisted-fred-key", preferred_store="file")
    status = auth_readiness_status()
    serialized = json.dumps(status)

    assert status["configured_keys"]["FRED_API_KEY"]["configured"] is True
    assert status["auth_kinds"]["fred"]["authenticated"] is True
    assert "file" in status["configured_keys"]["FRED_API_KEY"]["sources"]
    assert "persisted-fred-key" not in serialized


def test_api_data_gov_key_authenticates_fallback_kinds(monkeypatch: Any, tmp_path: Any) -> None:
    isolate_auth(monkeypatch, tmp_path)
    monkeypatch.setenv("API_DATA_GOV_KEY", "shared-data-gov-key")

    status = auth_readiness_status()

    for auth_kind in ("api_data_gov", "eia", "fda", "nrel"):
        assert status["auth_kinds"][auth_kind]["authenticated"] is True
        assert "API_DATA_GOV_KEY" in status["auth_kinds"][auth_kind]["configured_env"]
    assert "shared-data-gov-key" not in json.dumps(status)


def test_endpoint_auth_status_handles_no_auth_and_demo_fallback(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    isolate_auth(monkeypatch, tmp_path)

    missing_status = auth_readiness_status(include_endpoints=True)
    missing_records = {
        (record["agency_id"], record["endpoint_id"]): record
        for record in missing_status["endpoint_auth"]
    }
    assert "none" not in missing_status["auth_kinds"]
    assert missing_records[("datagov", "search")]["authenticated"] is True
    assert missing_records[("datagov", "search")]["auth_strategy"] == "none"
    assert missing_records[("fred", "series")]["authenticated"] is False

    monkeypatch.setenv("GOVDATA_ALLOW_DEMO_KEY", "1")
    demo_status = auth_readiness_status(include_endpoints=True)
    demo_records = {
        (record["agency_id"], record["endpoint_id"]): record
        for record in demo_status["endpoint_auth"]
    }
    food_record = demo_records[("agriculture", "food")]
    assert food_record["authenticated"] is True
    assert food_record["auth_strategy"] == "demo_key"
    assert food_record["demo_key_available"] is True
    assert demo_records[("fred", "series")]["authenticated"] is False
