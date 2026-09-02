#!/usr/bin/env python3
"""Validate repository contracts without requiring external services."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
EXCLUDED_PARTS = {
    ".git",
    ".local",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "htmlcov",
    "node_modules",
}


def repository_files(suffix: str) -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob(f"*{suffix}")
        if not any(part in EXCLUDED_PARTS for part in path.parts)
    )


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_documents(errors: list[str]) -> None:
    for path in repository_files(".json"):
        try:
            load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid JSON {path.relative_to(ROOT)}: {exc}")
    for suffix in (".yaml", ".yml"):
        for path in repository_files(suffix):
            try:
                with path.open(encoding="utf-8") as handle:
                    list(yaml.safe_load_all(handle))
            except (OSError, yaml.YAMLError) as exc:
                errors.append(f"invalid YAML {path.relative_to(ROOT)}: {exc}")
    for path in repository_files(".md"):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"invalid Markdown encoding {path.relative_to(ROOT)}: {exc}")
            continue
        if not content.strip():
            errors.append(f"empty Markdown document {path.relative_to(ROOT)}")


def validate_plugin(errors: list[str]) -> None:
    plugin_root = ROOT / "plugins/swim-coach"
    manifest_path = plugin_root / ".codex-plugin/plugin.json"
    marketplace_path = ROOT / ".agents/plugins/marketplace.json"
    manifest = load_json(manifest_path)
    marketplace = load_json(marketplace_path)

    if manifest.get("name") != "swim-coach":
        errors.append("plugin name must be swim-coach")
    version = manifest.get("version")
    if not isinstance(version, str) or not version.startswith("3.0.0+codex."):
        errors.append("P15 plugin version must use base 3.0.0 with one Codex cachebuster")
    capabilities = manifest.get("interface", {}).get("capabilities", [])
    if capabilities != ["Read", "Write"]:
        errors.append("P13 plugin must advertise Read and Write")
    if manifest.get("apps") != "./.app.json":
        errors.append("P06 manifest must reference the registered MCP app mapping")
    if "mcpServers" in manifest:
        errors.append("P06 manifest must use the registered app, not a bundled MCP server")
    skills_path = manifest.get("skills")
    if not isinstance(skills_path, str) or not (plugin_root / skills_path).is_dir():
        errors.append("plugin skills path is missing")
    skill_names = {path.parent.name for path in (plugin_root / "skills").glob("*/SKILL.md")}
    if skill_names != {
        "review-latest-swim",
        "goal-progress",
        "diagnose-sync",
        "adapt-workout",
        "publish-to-garmin",
        "post-swim-checkin",
        "plan-swim-week",
        "delete-workout",
    }:
        errors.append("P15 must contain exactly the eight personal ChatGPT-first skills")
    app_mapping = load_json(plugin_root / ".app.json")
    expected_app_mapping = {
        "apps": {
            "dev-6a7b7fbeceec819196c168888a9494b6": {
                "id": "asdk_app_6a7b7fbeceec819196c168888a9494b6"
            }
        }
    }
    if app_mapping != expected_app_mapping:
        errors.append("P06 app mapping must reference the registered Swim Coach connection")
    entries = [
        entry for entry in marketplace.get("plugins", []) if entry.get("name") == "swim-coach"
    ]
    if len(entries) != 1:
        errors.append("marketplace must contain exactly one swim-coach entry")


def validate_codex_project_mcp(errors: list[str]) -> None:
    config_path = PROJECT_ROOT / ".codex/config.toml"
    try:
        with config_path.open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"invalid project-scoped Codex config: {exc}")
        return

    server = config.get("mcp_servers", {}).get("swim_coach_p00")
    expected = {
        "url": "http://127.0.0.1:18000/mcp/",
        "enabled": True,
        "required": False,
        "enabled_tools": ["get_capabilities"],
        "default_tools_approval_mode": "auto",
        "startup_timeout_sec": 10,
        "tool_timeout_sec": 10,
    }
    if server != expected:
        errors.append("project Codex MCP config must expose only the safe P00 server policy")


def validate_contract_fixtures(errors: list[str]) -> None:
    schema = load_json(ROOT / "contracts/tool-result-envelope.schema.json")
    Draft202012Validator.check_schema(schema)
    from swim_coach.application.queries.get_capabilities import get_capabilities

    payload = get_capabilities().model_dump(mode="json")
    validation_errors = sorted(
        Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.path)
    )
    errors.extend(f"capability envelope: {item.message}" for item in validation_errors)


def main() -> int:
    errors: list[str] = []
    validate_documents(errors)
    validate_plugin(errors)
    validate_codex_project_mcp(errors)
    validate_contract_fixtures(errors)
    if errors:
        print("repository validation failed", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("repository validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
