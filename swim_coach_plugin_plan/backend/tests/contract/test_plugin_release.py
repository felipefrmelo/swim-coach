from __future__ import annotations

import hashlib
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
    "review-latest-swim": ("get_swims", "get_coach_context"),
    "goal-progress": ("get_coach_context",),
    "diagnose-sync": ("get_coach_context", "sync_garmin", "get_swims"),
    "adapt-workout": (
        "get_coach_context",
        "get_workouts",
        "save_workout",
        "publish_workout",
    ),
    "publish-to-garmin": (
        "get_workouts",
        "save_workout",
        "publish_workout",
    ),
    "post-swim-checkin": ("get_swims", "save_feedback"),
    "plan-swim-week": (
        "get_coach_context",
        "get_workouts",
        "get_swims",
        "generate_week",
        "publish_workout",
    ),
    "delete-workout": ("get_workouts", "delete_workout"),
}
CATEGORY_COUNTS = {
    "direct": 1,
    "indirect": 1,
    "followup": 1,
    "empty": 1,
    "auth": 1,
    "adversarial": 1,
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_eval_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for pattern in ("p13-*.yaml", "p14-*.yaml"):
        for path in sorted((ROOT / "tests/evals/cases").glob(pattern)):
            documents = yaml.safe_load_all(path.read_text(encoding="utf-8"))
            cases.extend(document for document in documents if document is not None)
    return cases


def test_p14_manifest_app_marketplace_and_release_matrix_include_direct_delete_2_1() -> None:
    manifest = load_json(PLUGIN_ROOT / ".codex-plugin/plugin.json")
    app_mapping = load_json(PLUGIN_ROOT / ".app.json")
    marketplace = load_json(ROOT / ".agents/plugins/marketplace.json")
    release_matrix = load_yaml(ROOT / "contracts/capability-release-matrix.yaml")

    assert manifest["name"] == "swim-coach"
    assert manifest["version"].startswith("2.1.0+codex.")
    assert manifest["skills"] == "./skills/"
    assert manifest["apps"] == "./.app.json"
    assert manifest["interface"]["capabilities"] == ["Read", "Write"]
    assert len(manifest["interface"]["defaultPrompt"]) == 8

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

    p08_release = next(item for item in release_matrix["plugin_releases"] if item["phase"] == "P08")
    assert p08_release["version"] == "0.2.0"
    assert p08_release["mode"] == "controlled-write"
    p09_release = next(item for item in release_matrix["plugin_releases"] if item["phase"] == "P09")
    assert p09_release["version"] == "0.3.0"
    assert p09_release["mode"] == "optional-ui"
    p10_release = next(item for item in release_matrix["plugin_releases"] if item["phase"] == "P10")
    assert p10_release["version"] == "0.4.0"
    assert p10_release["mode"] == "adaptive-planning"
    p12_release = next(item for item in release_matrix["plugin_releases"] if item["phase"] == "P12")
    assert p12_release["version"] == "1.0.0"
    assert p12_release["mode"] == "hardened-personal-release"
    p13_release = next(item for item in release_matrix["plugin_releases"] if item["phase"] == "P13")
    assert p13_release["version"] == "2.0.0"
    assert p13_release["mode"] == "chatgpt-first-direct-commands"
    assert p13_release["oauth_scopes"] == ["coach"]
    p14_release = next(item for item in release_matrix["plugin_releases"] if item["phase"] == "P14")
    assert p14_release["version"] == "2.1.0"
    assert p14_release["mode"] == "direct-delete-everywhere"
    assert p14_release["oauth_scopes"] == ["coach"]
    tool_names = {item["name"] for item in load_yaml(ROOT / "contracts/mcp-tools.yaml")["tools"]}
    assert tool_names == {item["name"] for item in release_matrix["tools"]}
    upgraded_skills = {
        item["name"]: tuple(item["required_tools"])
        for item in release_matrix["skills"]
        if item.get("introduced") in {"P13", "P14"}
    }
    assert upgraded_skills == SKILLS
    assert release_matrix["ui_resources"] == []


def test_p14_skill_frontmatter_workflows_and_ui_metadata_are_valid() -> None:
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

        referenced_names = set(re.findall(r"`([a-z][a-z0-9_]+)`", content))
        referenced_tools = referenced_names & {
            tool for canonical_tools in SKILLS.values() for tool in canonical_tools
        }
        assert referenced_tools == set(SKILLS[skill_name])

        agent_metadata = load_yaml(path.parent / "agents/openai.yaml")
        interface = agent_metadata["interface"]
        assert 25 <= len(interface["short_description"]) <= 64
        assert f"${skill_name}" in interface["default_prompt"]


def test_p14_eval_dataset_validates_direct_command_selection() -> None:
    schema = load_json(ROOT / "contracts/plugin-eval-case.schema.json")
    validator = Draft202012Validator(schema)
    tool_catalog = load_yaml(ROOT / "contracts/mcp-tools.yaml")
    tool_names = {item["name"] for item in tool_catalog["tools"]}
    cases = load_eval_cases()

    assert len(cases) == 48
    assert len({case["id"] for case in cases}) == len(cases)
    assert Counter(case["skill"] for case in cases) == Counter(
        {skill_name: 6 for skill_name in SKILLS}
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
        assert not {
            "get_action_proposal",
            "approve_action_proposal",
            "execute_approved_action",
            "preview_garmin_publish",
            "propose_week_plan",
        } & set(sequence)
        if "publish_workout" in sequence:
            assert expected["requires_confirmation"] is False

    for skill_name in SKILLS:
        skill_cases = [case for case in cases if case["skill"] == skill_name]
        counts = Counter(
            category
            for case in skill_cases
            for category in CATEGORY_COUNTS
            if f"_{category}_" in case["id"]
        )
        assert counts == Counter(CATEGORY_COUNTS), skill_name


def test_p14_release_manifest_hashes_are_current() -> None:
    release = load_json(ROOT / "releases/plugin-2.1.0.json")

    assert release["version"].startswith("2.1.0+codex.")
    assert release["mode"] == "direct-delete-everywhere"
    assert release["status"] == "release_candidate"
    assert release["oauth_scopes"] == ["coach"]
    assert len(release["tools"]) == 9
    for relative, expected in release["hashes"].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected, relative
