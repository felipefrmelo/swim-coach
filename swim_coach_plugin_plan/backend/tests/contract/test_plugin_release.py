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
    "review-latest-swim": (
        "list_recent_swims",
        "get_swim_activity",
        "get_sync_status",
    ),
    "goal-progress": ("get_training_context", "get_goal_progress"),
    "diagnose-sync": (
        "get_sync_status",
        "sync_garmin_activities",
        "get_job_status",
        "retry_failed_job",
    ),
    "adapt-workout": (
        "get_training_context",
        "get_today_workout",
        "get_week_plan",
        "propose_workout_change",
        "propose_workout_reschedule",
        "get_action_proposal",
    ),
    "publish-to-garmin": (
        "get_today_workout",
        "get_week_plan",
        "preview_garmin_publish",
        "get_action_proposal",
        "approve_action_proposal",
        "execute_approved_action",
        "get_job_status",
    ),
    "post-swim-checkin": (
        "list_recent_swims",
        "get_swim_activity",
        "record_session_feedback",
    ),
    "plan-swim-week": (
        "get_training_context",
        "get_week_plan",
        "list_recent_swims",
        "get_goal_progress",
        "get_sync_status",
        "propose_week_plan",
        "get_action_proposal",
    ),
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


def test_p12_manifest_app_marketplace_and_release_matrix_are_personal_1_0() -> None:
    manifest = load_json(PLUGIN_ROOT / ".codex-plugin/plugin.json")
    app_mapping = load_json(PLUGIN_ROOT / ".app.json")
    marketplace = load_json(ROOT / ".agents/plugins/marketplace.json")
    release_matrix = load_yaml(ROOT / "contracts/capability-release-matrix.yaml")

    assert manifest["name"] == "swim-coach"
    assert manifest["version"] == "1.0.0"
    assert manifest["skills"] == "./skills/"
    assert manifest["apps"] == "./.app.json"
    assert manifest["interface"]["capabilities"] == ["Read", "Write"]
    assert len(manifest["interface"]["defaultPrompt"]) == 7

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
    released_skills = {
        item["name"]
        for item in release_matrix["skills"]
        if item.get("introduced") in {"P06", "P08", "P10"}
    }
    assert released_skills == set(SKILLS)
    assert {item["name"] for item in release_matrix["ui_resources"]} == {
        "workout-card",
        "swim-comparison-card",
        "goal-progress-card",
        "proposal-confirmation-card",
        "sync-status-card",
    }


def test_p10_skill_frontmatter_workflows_and_ui_metadata_are_valid() -> None:
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


def test_p10_eval_dataset_validates_selection_order_and_confirmation_boundaries() -> None:
    schema = load_json(ROOT / "contracts/plugin-eval-case.schema.json")
    validator = Draft202012Validator(schema)
    tool_catalog = load_yaml(ROOT / "contracts/mcp-tools.yaml")
    tool_names = {item["name"] for item in tool_catalog["tools"]}
    cases = load_eval_cases()

    assert len(cases) == 154
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
        if "approve_action_proposal" in sequence or "execute_approved_action" in sequence:
            assert case["skill"] == "publish-to-garmin"
            assert len(case["user_turns"]) >= 2 or case.get("fixtures", {}).get("prior_turn")
        if len(case["user_turns"]) == 1 and "preview_garmin_publish" in sequence:
            assert "approve_action_proposal" not in sequence
            assert "execute_approved_action" not in sequence
        if (
            case["skill"] == "publish-to-garmin"
            and "preview_garmin_publish" in sequence
            and "approve_action_proposal" not in sequence
            and "auth" not in case.get("fixtures", {})
        ):
            assert expected["requires_confirmation"] is True
        if case["skill"] == "plan-swim-week":
            assert "approve_action_proposal" not in sequence
            assert "execute_approved_action" not in sequence
            assert "preview_garmin_publish" not in sequence

    for skill_name in SKILLS:
        skill_cases = [case for case in cases if case["skill"] == skill_name]
        counts = Counter(
            category
            for case in skill_cases
            for category in CATEGORY_COUNTS
            if f"_{category}_" in case["id"]
        )
        assert counts == Counter(CATEGORY_COUNTS), skill_name


def test_p12_release_manifest_hashes_are_current() -> None:
    release = load_json(ROOT / "releases/plugin-1.0.0.json")

    assert release["version"] == "1.0.0"
    assert release["mode"] == "hardened-personal-release"
    assert release["status"] == "release_candidate"
    assert release["verification"]["image_high_critical_vulnerabilities"] == 0
    for relative, expected in release["hashes"].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected, relative
