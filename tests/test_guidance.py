from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from govdata_mcp.auth_store import PERSISTABLE_ENV_NAMES, save_persisted_secret
from govdata_mcp.guidance import GUIDANCE_TOPICS, guidance_payload
from govdata_mcp.server import (
    auth_resource,
    auth_status_resource,
    govdata_list_agencies,
    govdata_auth_status,
    govdata_guidance,
    guide_agency_notes_resource,
    guide_examples_resource,
    guide_resource,
    guide_workflow_resource,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_guidance_topics_are_json_serializable() -> None:
    for topic in GUIDANCE_TOPICS:
        payload = guidance_payload(topic)
        assert payload["topic"] == topic
        assert "available_topics" in payload
        json.dumps(payload)


def test_guidance_tool_defaults_to_overview() -> None:
    payload = run(govdata_guidance())

    assert payload["topic"] == "overview"
    assert "overview" in payload
    assert "govdata_query" in payload["overview"]["start_here"]
    assert "govdata_find_dataset" in payload["overview"]["start_here"]
    assert "govdata_get_dataset" in payload["overview"]["start_here"]
    assert "govdata://auth/status" in payload["overview"]["mcp_resources"]


def test_guidance_resources_serialize() -> None:
    guide = json.loads(guide_resource())
    workflow = json.loads(guide_workflow_resource())
    agency_notes = json.loads(guide_agency_notes_resource())
    examples = json.loads(guide_examples_resource())

    assert guide["topic"] == "all"
    assert "workflow" in workflow
    assert "datasets" in guide
    assert "census" in agency_notes["agency_notes"]
    assert any("govdata_query" in example for example in examples["examples"])
    assert any("govdata_find_dataset" in example for example in examples["examples"])
    assert any("govdata_get_dataset" in example for example in examples["examples"])
    assert "ipums_create_extract" not in json.dumps(guide)
    assert "ipums_download_extract" not in json.dumps(guide)


def test_auth_status_tool_and_resources_serialize_without_secret_values(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setenv("GOVDATA_AUTH_DISABLE_KEYRING", "1")
    monkeypatch.setenv("GOVDATA_SECRETS_FILE", str(tmp_path / "secrets.env"))
    for name in PERSISTABLE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    save_persisted_secret("FRED_API_KEY", "server-test-fred-key", preferred_store="file")

    tool_payload = run(govdata_auth_status(include_endpoints=True))
    resource_payload = json.loads(auth_status_resource())
    auth_payload = json.loads(auth_resource())
    serialized = json.dumps(
        {
            "tool": tool_payload,
            "resource": resource_payload,
            "auth": auth_payload,
        }
    )

    assert tool_payload["auth_kinds"]["fred"]["authenticated"] is True
    assert resource_payload["auth_kinds"]["fred"]["authenticated"] is True
    assert "none" not in tool_payload["auth_kinds"]
    assert "none" not in resource_payload["auth_kinds"]
    assert "none" not in auth_payload["auth_env_by_kind"]
    assert auth_payload["status_tool"] == "govdata_auth_status"
    assert auth_payload["status_resource"] == "govdata://auth/status"
    assert "server-test-fred-key" not in serialized


def test_auth_guidance_uses_installed_console_scripts() -> None:
    guidance_auth = guidance_payload("auth")["auth"]
    auth_payload = json.loads(auth_resource())
    serialized = json.dumps({"guidance": guidance_auth, "resource": auth_payload})

    assert guidance_auth["setup_command"] == "govdata-auth setup"
    assert guidance_auth["inspect_command"] == "govdata-auth list"
    assert guidance_auth["path_command"] == "govdata-auth path"
    assert guidance_auth["delete_example"] == "govdata-auth delete FRED_API_KEY"
    assert auth_payload["setup_command"] == "govdata-auth setup"
    assert "uv --directory" not in serialized
    assert "ipums_create_extract" not in serialized
    assert "ipums_download_extract" not in serialized


def test_guidance_examples_do_not_include_secret_keys() -> None:
    examples = guidance_payload("examples")["examples"]

    assert not any("API_KEY" in example or "api_key" in example for example in examples)
    assert not any("FRED_API_KEY" in example for example in examples)


def test_list_agencies_stays_lightweight() -> None:
    payload = run(govdata_list_agencies(include_planned=True))
    endpoint = payload["agencies"][0]["endpoints"][0]

    assert "examples" not in endpoint
    assert "schema" not in endpoint
    assert "common_gotchas" not in endpoint


def test_mcp_configs_use_installed_command() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config_paths = [
        repo_root / ".mcp.json",
    ]

    for path in config_paths:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        server = data["mcpServers"]["govdata"]
        assert server == {"command": "govdata-mcp"}
        assert "--directory" not in text
        assert "plugins/govdata" not in text
        assert '"cwd"' not in text


def test_readme_documents_global_install_for_claude_and_codex() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    assert "python3 install.py --all" in readme
    assert "python3 install.py --claude" in readme
    assert "python3 install.py --codex" in readme
    assert "govdata-auth setup" in readme
    assert "uv run python -c" in readme
    assert "plugins/govdata" not in readme
    assert "uv --directory plugins/govdata run govdata-auth" not in readme


def test_live_docs_and_plugin_manifest_do_not_reference_removed_skills() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    live_paths = [
        repo_root / "README.md",
        repo_root / "CLAUDE.md",
        repo_root / "AGENTS.md",
        repo_root / ".codex-plugin" / "plugin.json",
        *sorted((repo_root / "docs").glob("*.md")),
    ]
    stale_terms = (
        "/govdata-claude",
        "$govdata-codex",
        ".claude/skills/govdata-claude",
        "plugins/govdata/skills/govdata-codex",
        '"skills"',
    )

    for path in live_paths:
        text = path.read_text(encoding="utf-8")
        for term in stale_terms:
            assert term not in text, f"{term} found in {path}"

    assert not (repo_root / ".claude" / "skills").exists()
    assert not (repo_root / "plugins" / "govdata" / "skills").exists()


def test_examples_folder_is_removed_and_docs_are_canonical() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    docs_dir = repo_root / "docs"

    assert not (repo_root / "examples").exists()
    assert (docs_dir / "README.md").exists()
    assert (docs_dir / "tools.md").exists()
    assert (docs_dir / "workflows.md").exists()
    assert (docs_dir / "testing.md").exists()
