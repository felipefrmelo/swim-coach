from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins/swim-coach"
SKILLS = {
    "review-latest-swim": (
        "list_recent_swims",
        "get_swim_activity",
        "get_sync_status",
    ),
    "goal-progress": ("get_training_context", "get_goal_progress"),
    "diagnose-sync": ("get_sync_status",),
}
CATEGORY_COUNTS = {
    "direct": 5,
    "indirect": 5,
    "followup": 3,
    "empty": 3,
    "auth": 3,
    "adversarial": 3,
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_eval_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted((ROOT / "tests/evals/cases").glob("*.yaml")):
        documents = yaml.safe_load_all(path.read_text(encoding="utf-8"))
        cases.extend(document for document in documents if document is not None)
    return cases


def test_p06_manifest_app_marketplace_and_release_matrix_are_read_only() -> None:
    manifest = load_json(PLUGIN_ROOT / ".codex-plugin/plugin.json")
    app_mapping = load_json(PLUGIN_ROOT / ".app.json")
    marketplace = load_json(ROOT / ".agents/plugins/marketplace.json")
    release_matrix = load_yaml(ROOT / "contracts/capability-release-matrix.yaml")

    assert manifest["name"] == "swim-coach"
    assert manifest["version"] == "0.1.0"
    assert manifest["skills"] == "./skills/"
    assert manifest["apps"] == "./.app.json"
    assert manifest["interface"]["capabilities"] == ["Read"]
    assert len(manifest["interface"]["defaultPrompt"]) == 3
    assert "Write" not in manifest["interface"]["capabilities"]

    assert app_mapping == {
        "apps": {
            "dev-6a7b7fbeceec819196c168888a9494b6": {
                "id": "asdk_app_6a7b7fbeceec819196c168888a9494b6"
            }
        }
    }
    entries = [entry for entry in marketplace["plugins"] if entry["name"] == "swim-coach"]
    assert entries == [
        {
            "name": "swim-coach",
            "source": {"source": "local", "path": "./plugins/swim-coach"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Health & Fitness",
        }
    ]

    p06_release = next(item for item in release_matrix["plugin_releases"] if item["phase"] == "P06")
    assert p06_release["version"] == "0.1.0"
    assert p06_release["mode"] == "read-only"
    released_skills = {
        item["name"] for item in release_matrix["skills"] if item.get("introduced") == "P06"
    }
    assert released_skills == set(SKILLS)


def test_p06_skill_frontmatter_workflows_and_ui_metadata_are_valid() -> None:
    skill_files = sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))
    assert {path.parent.name for path in skill_files} == set(SKILLS)

    for path in skill_files:
        content = path.read_text(encoding="utf-8")
        match = re.match(r"\A---\n(?P<frontmatter>.*?)\n---\n", content, re.DOTALL)
        assert match is not None
        frontmatter = yaml.safe_load(match.group("frontmatter"))
        skill_name = path.parent.name
        assert frontmatter.keys() == {"name", "description"}
        assert frontmatter["name"] == skill_name
        assert len(frontmatter["description"]) >= 80
        assert "TODO" not in content

        referenced_tools = set(re.findall(r"`([a-z][a-z0-9_]+)`", content))
        assert referenced_tools == set(SKILLS[skill_name])

        agent_metadata = load_yaml(path.parent / "agents/openai.yaml")
        interface = agent_metadata["interface"]
        assert 25 <= len(interface["short_description"]) <= 64
        assert f"${skill_name}" in interface["default_prompt"]


def test_p06_eval_dataset_validates_selection_order_and_write_negatives() -> None:
    schema = load_json(ROOT / "contracts/plugin-eval-case.schema.json")
    validator = Draft202012Validator(schema)
    tool_catalog = load_yaml(ROOT / "contracts/mcp-tools.yaml")
    tool_names = {item["name"] for item in tool_catalog["tools"]}
    release_matrix = load_yaml(ROOT / "contracts/capability-release-matrix.yaml")
    write_tools = {item["name"] for item in release_matrix["tools"] if item["kind"] != "read"}
    cases = load_eval_cases()

    assert len(cases) == 66
    assert len({case["id"] for case in cases}) == len(cases)
    assert Counter(case["skill"] for case in cases) == Counter(
        {skill_name: 22 for skill_name in SKILLS}
    )

    for case in cases:
        assert not list(validator.iter_errors(case)), case["id"]
        skill_name = case["skill"]
        expected = case["expect"]
        sequence = expected["tool_sequence"]
        canonical_order = SKILLS[skill_name]
        indices = [canonical_order.index(tool) for tool in sequence]
        assert indices == sorted(indices), case["id"]
        assert set(sequence) <= set(canonical_order) <= tool_names
        assert set(sequence).isdisjoint(write_tools)
        assert expected["requires_confirmation"] is False
        if "_adversarial_" in case["id"]:
            assert set(expected["forbidden_tools"]) == write_tools

    for skill_name in SKILLS:
        skill_cases = [case for case in cases if case["skill"] == skill_name]
        counts = Counter(
            category
            for case in skill_cases
            for category in CATEGORY_COUNTS
            if f"_{category}_" in case["id"]
        )
        assert counts == Counter(CATEGORY_COUNTS), skill_name
