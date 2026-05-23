from __future__ import annotations

import argparse
import getpass
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Literal

from .registry import AGENCIES, AUTH_ENV, AuthKind, Endpoint


StoreName = Literal["environment", "keyring", "file"]
PreferredStore = Literal["auto", "keyring", "file"]

SERVICE_NAME = "govdata-mcp"
KEYRING_DISABLED_ENV = "GOVDATA_AUTH_DISABLE_KEYRING"
SECRETS_FILE_ENV = "GOVDATA_SECRETS_FILE"
DEMO_KEY_FLAG = "GOVDATA_ALLOW_DEMO_KEY"
TRUTHY = {"1", "true", "yes", "y", "on"}


def _ordered_auth_env_names() -> tuple[str, ...]:
    names: list[str] = []
    for env_names in AUTH_ENV.values():
        for name in env_names:
            if name not in names:
                names.append(name)
    return tuple(names)


SECRET_ENV_NAMES = _ordered_auth_env_names()
PERSISTABLE_ENV_NAMES = (*SECRET_ENV_NAMES, DEMO_KEY_FLAG)
_PERSISTABLE_SET = set(PERSISTABLE_ENV_NAMES)

_LOADED = False


def load_persisted_auth(*, force: bool = False) -> None:
    """Load locally persisted auth values into os.environ without overriding it."""
    global _LOADED

    if _LOADED and not force:
        return

    file_values = read_file_secrets()
    for name in PERSISTABLE_ENV_NAMES:
        if os.getenv(name):
            continue
        value = get_keyring_secret(name)
        if value is None:
            value = file_values.get(name)
        if value:
            os.environ[name] = value

    _LOADED = True


def config_dir() -> Path:
    configured = os.getenv("XDG_CONFIG_HOME")
    if configured:
        return Path(configured).expanduser() / SERVICE_NAME
    return Path.home() / ".config" / SERVICE_NAME


def secrets_file_path() -> Path:
    configured = os.getenv(SECRETS_FILE_ENV)
    if configured:
        return Path(configured).expanduser()
    return config_dir() / "secrets.env"


def validate_name(name: str) -> str:
    if name not in _PERSISTABLE_SET:
        allowed = ", ".join(PERSISTABLE_ENV_NAMES)
        raise ValueError(f"Unsupported GovData auth name '{name}'. Supported names: {allowed}")
    return name


def validate_value(value: str) -> str:
    if "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError("Secret values must be single-line strings.")
    if not value:
        raise ValueError("Secret value must not be empty.")
    return value


def read_file_secrets(path: Path | None = None) -> dict[str, str]:
    path = path or secrets_file_path()
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            parts = shlex.split(stripped, comments=True, posix=True)
        except ValueError:
            continue
        if not parts or "=" not in parts[0]:
            continue
        name, value = parts[0].split("=", 1)
        if name in _PERSISTABLE_SET and value:
            values[name] = value
    return values


def save_file_secret(name: str, value: str) -> None:
    name = validate_name(name)
    value = validate_value(value)
    values = read_file_secrets()
    values[name] = value
    write_file_secrets(values)


def delete_file_secret(name: str) -> bool:
    name = validate_name(name)
    values = read_file_secrets()
    existed = name in values
    values.pop(name, None)
    write_file_secrets(values)
    return existed


def write_file_secrets(values: dict[str, str]) -> None:
    path = secrets_file_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass

    clean_values = {
        validate_name(name): validate_value(value)
        for name, value in values.items()
        if name in _PERSISTABLE_SET and value
    }
    lines = [
        "# GovData MCP local auth values.",
        "# This file is read by govdata-mcp on startup. Do not commit it.",
        "",
    ]
    for name in PERSISTABLE_ENV_NAMES:
        value = clean_values.get(name)
        if value:
            lines.append(f"{name}={quote_env_value(value)}")

    tmp_path = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).rstrip() + "\n")
        os.replace(tmp_path, path)
        path.chmod(0o600)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def quote_env_value(value: str) -> str:
    return shlex.quote(value)


def keyring_available() -> tuple[bool, str | None]:
    if os.getenv(KEYRING_DISABLED_ENV):
        return False, f"{KEYRING_DISABLED_ENV} is set"
    try:
        import keyring  # type: ignore[import-not-found]

        backend = keyring.get_keyring()
    except Exception as exc:
        return False, str(exc)

    backend_name = backend.__class__.__module__ + "." + backend.__class__.__name__
    if "fail" in backend_name.lower():
        return False, backend_name
    return True, backend_name


def get_keyring_secret(name: str) -> str | None:
    validate_name(name)
    available, _ = keyring_available()
    if not available:
        return None
    try:
        import keyring  # type: ignore[import-not-found]

        return keyring.get_password(SERVICE_NAME, name)
    except Exception:
        return None


def save_keyring_secret(name: str, value: str) -> bool:
    name = validate_name(name)
    value = validate_value(value)
    available, _ = keyring_available()
    if not available:
        return False
    try:
        import keyring  # type: ignore[import-not-found]

        keyring.set_password(SERVICE_NAME, name, value)
        return True
    except Exception:
        return False


def delete_keyring_secret(name: str) -> bool:
    name = validate_name(name)
    available, _ = keyring_available()
    if not available:
        return False
    try:
        import keyring  # type: ignore[import-not-found]

        keyring.delete_password(SERVICE_NAME, name)
        return True
    except Exception:
        return False


def save_persisted_secret(name: str, value: str, *, preferred_store: PreferredStore = "auto") -> StoreName:
    validate_name(name)
    validate_value(value)

    if preferred_store in {"auto", "keyring"} and save_keyring_secret(name, value):
        return "keyring"
    if preferred_store == "keyring":
        raise RuntimeError("OS keyring is unavailable. Use --store file to save to secrets.env.")

    save_file_secret(name, value)
    return "file"


def delete_persisted_secret(name: str) -> list[StoreName]:
    validate_name(name)
    removed: list[StoreName] = []
    if delete_keyring_secret(name):
        removed.append("keyring")
    if delete_file_secret(name):
        removed.append("file")
    return removed


def secret_sources(name: str) -> list[StoreName]:
    validate_name(name)
    sources: list[StoreName] = []
    if os.getenv(name):
        sources.append("environment")
    if get_keyring_secret(name):
        sources.append("keyring")
    if read_file_secrets().get(name):
        sources.append("file")
    return sources


def auth_status() -> dict[str, Any]:
    available, detail = keyring_available()
    return {
        "service_name": SERVICE_NAME,
        "keyring_available": available,
        "keyring_detail": detail,
        "secrets_file": str(secrets_file_path()),
        "secret_env_names": list(SECRET_ENV_NAMES),
        "persistable_env_names": list(PERSISTABLE_ENV_NAMES),
        "load_order": ["environment", "keyring", "file"],
    }


def env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUTHY


def configured_key_status() -> dict[str, dict[str, Any]]:
    """Return safe configured/not-configured status for each supported auth name."""
    load_persisted_auth()
    status: dict[str, dict[str, Any]] = {}
    for name in PERSISTABLE_ENV_NAMES:
        sources = secret_sources(name)
        entry: dict[str, Any] = {
            "configured": bool(sources),
            "sources": sources,
        }
        if name == DEMO_KEY_FLAG:
            entry["enabled"] = env_truthy(name)
        status[name] = entry
    return status


def auth_kind_status(
    key_status: dict[str, dict[str, Any]] | None = None,
) -> dict[AuthKind, dict[str, Any]]:
    """Return which auth kinds have at least one configured key available."""
    key_status = key_status or configured_key_status()
    statuses: dict[AuthKind, dict[str, Any]] = {}
    for auth_kind, env_names in AUTH_ENV.items():
        configured_env = [
            name
            for name in env_names
            if key_status.get(name, {}).get("configured", False)
        ]
        missing_env = [name for name in env_names if name not in configured_env]
        statuses[auth_kind] = {
            "authenticated": auth_kind == "none" or bool(configured_env),
            "env": list(env_names),
            "configured_env": configured_env,
            "missing_env": missing_env,
        }
    return statuses


def auth_kind_status_for_view(
    kind_status: dict[AuthKind, dict[str, Any]],
) -> dict[AuthKind, dict[str, Any]]:
    """Return auth kinds that require user-configurable credentials."""
    endpoint_counts: dict[AuthKind, int] = {auth_kind: 0 for auth_kind in kind_status}
    for agency in AGENCIES.values():
        if agency.status != "active":
            continue
        for endpoint in agency.endpoints.values():
            if endpoint.status == "active":
                endpoint_counts[endpoint.auth] = endpoint_counts.get(endpoint.auth, 0) + 1
    return {
        auth_kind: {
            **status,
            "endpoint_count": endpoint_counts.get(auth_kind, 0),
            "endpoint_backed": endpoint_counts.get(auth_kind, 0) > 0,
        }
        for auth_kind, status in kind_status.items()
        if auth_kind != "none"
    }


def endpoint_auth_record(
    agency_id: str,
    endpoint: Endpoint,
    *,
    key_status: dict[str, dict[str, Any]],
    kind_status: dict[AuthKind, dict[str, Any]],
) -> dict[str, Any]:
    env_names = list(AUTH_ENV[endpoint.auth])
    configured_env = [
        name
        for name in env_names
        if key_status.get(name, {}).get("configured", False)
    ]
    demo_key_available = bool(
        endpoint.demo_key and key_status.get(DEMO_KEY_FLAG, {}).get("enabled", False)
    )
    authenticated = bool(kind_status[endpoint.auth]["authenticated"] or demo_key_available)
    if endpoint.auth == "none":
        auth_strategy = "none"
    elif configured_env:
        auth_strategy = "configured_key"
    elif demo_key_available:
        auth_strategy = "demo_key"
    else:
        auth_strategy = "missing_key"

    return {
        "agency_id": agency_id,
        "endpoint_id": endpoint.id,
        "auth": endpoint.auth,
        "auth_env": env_names,
        "configured_env": configured_env,
        "missing_env": [name for name in env_names if name not in configured_env],
        "authenticated": authenticated,
        "auth_strategy": auth_strategy,
        "auth_location": endpoint.auth_location,
        "auth_name": endpoint.auth_name,
        "demo_key_supported": endpoint.demo_key is not None,
        "demo_key_available": demo_key_available,
    }


def endpoint_auth_status(
    *,
    key_status: dict[str, dict[str, Any]] | None = None,
    kind_status: dict[AuthKind, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return safe auth readiness for active registered endpoints."""
    key_status = key_status or configured_key_status()
    kind_status = kind_status or auth_kind_status(key_status)
    records: list[dict[str, Any]] = []
    for agency in AGENCIES.values():
        if agency.status != "active":
            continue
        for endpoint in agency.endpoints.values():
            records.append(
                endpoint_auth_record(
                    agency.id,
                    endpoint,
                    key_status=key_status,
                    kind_status=kind_status,
                )
            )
    return records


def auth_readiness_status(*, include_endpoints: bool = False) -> dict[str, Any]:
    """Return MCP-facing auth readiness without exposing secret values."""
    load_persisted_auth(force=True)
    key_status = configured_key_status()
    kind_status = auth_kind_status(key_status)
    persistent_auth = auth_status()
    payload: dict[str, Any] = {
        "service_name": SERVICE_NAME,
        "secrets_file": persistent_auth["secrets_file"],
        "keyring_available": persistent_auth["keyring_available"],
        "keyring_detail": persistent_auth["keyring_detail"],
        "load_order": persistent_auth["load_order"],
        "configured_keys": key_status,
        "auth_kinds": auth_kind_status_for_view(kind_status),
        "demo_key_fallback": {
            "flag": DEMO_KEY_FLAG,
            "enabled": bool(key_status.get(DEMO_KEY_FLAG, {}).get("enabled", False)),
            "note": (
                "Only endpoints that declare demo-key support can use DEMO_KEY, "
                "and only when this flag is enabled."
            ),
        },
        "notes": [
            "Secret values are intentionally omitted.",
            "Blank setup entries are skipped and treated as not configured.",
            "Environment variables override persisted keyring or file values.",
            (
                "An endpoint is marked authenticated when its auth kind has a configured "
                "key, when it needs no auth, or when endpoint-specific demo-key fallback "
                "is enabled."
            ),
        ],
    }
    if include_endpoints:
        payload["endpoint_auth"] = endpoint_auth_status(
            key_status=key_status,
            kind_status=kind_status,
        )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="govdata-auth",
        description="Configure persistent local API keys for the GovData MCP server.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser("setup", help="Interactively save API keys.")
    setup_parser.add_argument("--store", choices=("auto", "keyring", "file"), default="auto")

    list_parser = subparsers.add_parser("list", help="Show which auth values are configured.")
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    set_parser = subparsers.add_parser("set", help="Save one API key or auth setting.")
    set_parser.add_argument("name", choices=PERSISTABLE_ENV_NAMES)
    set_parser.add_argument("--store", choices=("auto", "keyring", "file"), default="auto")
    set_parser.add_argument("--value-stdin", action="store_true", help="Read the secret value from stdin.")

    delete_parser = subparsers.add_parser("delete", help="Delete one persisted API key or auth setting.")
    delete_parser.add_argument("name", choices=PERSISTABLE_ENV_NAMES)

    subparsers.add_parser("path", help="Show auth storage paths and keyring availability.")

    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            return _cmd_setup(args.store)
        if args.command == "list":
            return _cmd_list(json_output=args.json)
        if args.command == "set":
            return _cmd_set(args.name, store=args.store, value_stdin=args.value_stdin)
        if args.command == "delete":
            return _cmd_delete(args.name)
        if args.command == "path":
            return _cmd_path()
    except (RuntimeError, ValueError) as exc:
        print(f"govdata-auth: {exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_setup(store: PreferredStore) -> int:
    print("GovData MCP persistent auth setup")
    print("Environment variables still override saved values. Press Enter to skip or keep an existing value.")
    available, detail = keyring_available()
    if store == "auto":
        target = "OS keyring" if available else f"secrets file at {secrets_file_path()}"
    elif store == "keyring":
        target = "OS keyring"
    else:
        target = f"secrets file at {secrets_file_path()}"
    print(f"Storage target: {target}")
    if detail:
        print(f"Keyring: {detail}")
    print("")

    saved = 0
    for name in SECRET_ENV_NAMES:
        sources = secret_sources(name)
        status = ", ".join(sources) if sources else "not set"
        value = getpass.getpass(f"{name} [{status}] (blank to skip): ")
        if not value:
            continue
        saved_to = save_persisted_secret(name, value, preferred_store=store)
        print(f"Saved {name} to {saved_to}.")
        saved += 1

    print(f"Saved {saved} value(s). Restart Claude Code or Codex MCP sessions to pick up changes.")
    return 0


def _cmd_list(*, json_output: bool = False) -> int:
    status = auth_status()
    entries = {name: secret_sources(name) for name in PERSISTABLE_ENV_NAMES}
    if json_output:
        import json

        print(json.dumps({"auth": status, "entries": entries}, indent=2))
        return 0

    print(f"Service: {status['service_name']}")
    print(f"Keyring available: {status['keyring_available']} ({status['keyring_detail']})")
    print(f"Secrets file: {status['secrets_file']}")
    print("Load order: environment > keyring > file")
    print("")
    for name, sources in entries.items():
        source_text = ", ".join(sources) if sources else "not set"
        print(f"{name}: {source_text}")
    return 0


def _cmd_set(name: str, *, store: PreferredStore, value_stdin: bool) -> int:
    if value_stdin:
        value = sys.stdin.read().strip()
    else:
        value = getpass.getpass(f"{name}: ")
    saved_to = save_persisted_secret(name, value, preferred_store=store)
    print(f"Saved {name} to {saved_to}.")
    return 0


def _cmd_delete(name: str) -> int:
    removed = delete_persisted_secret(name)
    if removed:
        print(f"Deleted {name} from {', '.join(removed)}.")
    else:
        print(f"No persisted value found for {name}.")
    print("Environment variables in your shell or MCP client config are unchanged.")
    return 0


def _cmd_path() -> int:
    status = auth_status()
    print(f"Service: {status['service_name']}")
    print(f"Keyring available: {status['keyring_available']} ({status['keyring_detail']})")
    print(f"Secrets file: {status['secrets_file']}")
    print("Load order: environment > keyring > file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
