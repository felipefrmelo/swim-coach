#!/usr/bin/env python3
"""Validate the modular Swim Coach implementation plan.

Run from any directory:
    python tools/validate_plan.py

Optional:
    python tools/validate_plan.py --write-report
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

try:
    import jsonschema  # type: ignore
except ImportError:  # pragma: no cover
    jsonschema = None

ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {
    ".git",
    ".hypothesis",
    ".local",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vite",
    "__pycache__",
    "dist",
    "htmlcov",
    "node_modules",
    "playwright-report",
    "test-results",
}


def repository_files(pattern: str = "*") -> list[Path]:
    return [
        path
        for path in ROOT.rglob(pattern)
        if path.is_file() and not any(part in IGNORED_DIRS for part in path.parts)
    ]


@dataclass
class Report:
    checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def check(self, message: str) -> None:
        self.checks.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)


def load_json(path: Path, report: Report) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        report.error(f"JSON inválido em {path.relative_to(ROOT)}: {exc}")
        return None


def load_yaml(path: Path, report: Report) -> Any | None:
    if yaml is None:
        report.warn("PyYAML não instalado; arquivos YAML não foram parseados.")
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        report.error(f"YAML inválido em {path.relative_to(ROOT)}: {exc}")
        return None


def validate_required_structure(report: Report) -> None:
    required = [
        "README.md",
        "LLM_START_HERE.md",
        "MASTER_PLAN.md",
        "AGENTS.md",
        "IMPLEMENTATION_STATUS.md",
        "implementation-status.json",
        "plan-manifest.json",
        "docs/02-domain-object-catalog.md",
        "docs/09-mcp-tool-contracts.md",
        "docs/20-context-map.md",
        "contracts/canonical-workout.schema.json",
        "contracts/mcp-tools.yaml",
        "contracts/capability-release-matrix.yaml",
        "plugin-blueprint/.codex-plugin/plugin.json",
    ]
    for rel in required:
        if not (ROOT / rel).exists():
            report.error(f"Arquivo obrigatório ausente: {rel}")
    for phase in range(13):
        if not list((ROOT / "phases").glob(f"p{phase:02d}-*.md")):
            report.error(f"Fase P{phase:02d} ausente")
        if not (ROOT / "prompts" / f"p{phase:02d}.md").exists():
            report.error(f"Prompt P{phase:02d} ausente")
    report.check("estrutura obrigatória e 13 fases/prompts")


def validate_json_yaml(report: Report) -> dict[Path, Any]:
    parsed: dict[Path, Any] = {}
    for path in repository_files("*.json"):
        data = load_json(path, report)
        if data is not None:
            parsed[path] = data
    for path in repository_files("*.yaml"):
        data = load_yaml(path, report)
        if data is not None:
            parsed[path] = data
    report.stats["json_files"] = len(repository_files("*.json"))
    report.stats["yaml_files"] = len(repository_files("*.yaml"))
    report.check("parse de JSON/YAML")
    return parsed


def validate_schemas(parsed: dict[Path, Any], report: Report) -> None:
    if jsonschema is None:
        report.warn("jsonschema não instalado; schemas/exemplos não foram validados semanticamente.")
        return

    schemas: dict[str, Any] = {}
    for path in (ROOT / "contracts").glob("*.schema.json"):
        schema = parsed.get(path)
        if schema is None:
            continue
        try:
            jsonschema.validators.validator_for(schema).check_schema(schema)
            schemas[path.name] = schema
        except Exception as exc:  # noqa: BLE001
            report.error(f"JSON Schema inválido em {path.name}: {exc}")

    bindings = {
        ROOT / "implementation-status.json": "implementation-status.schema.json",
        ROOT / "examples/workout-technique-1600m-20m.json": "canonical-workout.schema.json",
        ROOT / "examples/action-proposal-garmin-publish.json": "action-proposal.schema.json",
        ROOT / "examples/tool-result-latest-swim.json": "tool-result-envelope.schema.json",
    }
    for path, schema_name in bindings.items():
        instance = parsed.get(path)
        schema = schemas.get(schema_name)
        if instance is None or schema is None:
            continue
        try:
            jsonschema.validate(instance=instance, schema=schema, format_checker=jsonschema.FormatChecker())
        except Exception as exc:  # noqa: BLE001
            report.error(f"Exemplo {path.relative_to(ROOT)} não atende {schema_name}: {exc}")

    eval_schema = schemas.get("plugin-eval-case.schema.json")
    if eval_schema is not None:
        for path in (ROOT / "evals/cases").glob("*.yaml"):
            instance = parsed.get(path)
            if instance is None:
                continue
            try:
                jsonschema.validate(instance=instance, schema=eval_schema)
            except Exception as exc:  # noqa: BLE001
                report.error(f"Eval {path.name} inválida: {exc}")

    report.check("JSON Schemas, status, exemplos e evals")


def validate_markdown(report: Report) -> None:
    link_re = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
    markdown = repository_files("*.md")
    for path in markdown:
        text = path.read_text(encoding="utf-8")
        fences = [line for line in text.splitlines() if line.lstrip().startswith("```")]
        if len(fences) % 2:
            report.error(f"Fence Markdown não fechado em {path.relative_to(ROOT)}")
        if path.name == "SKILL.md":
            lines = text.splitlines()
            if not lines or lines[0] != "---" or lines[1:].count("---") < 1:
                report.error(f"Frontmatter ausente/incompleto em {path.relative_to(ROOT)}")
        for target in link_re.findall(text):
            target = target.strip()
            if not target or target.startswith(("#", "http://", "https://", "mailto:", "sandbox:", "plugin://")):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            destination = (path.parent / target).resolve()
            try:
                destination.relative_to(ROOT.resolve())
            except ValueError:
                report.error(f"Link sai do pacote: {path.relative_to(ROOT)} -> {target}")
                continue
            if not destination.exists():
                report.error(f"Link quebrado: {path.relative_to(ROOT)} -> {target}")
    report.stats["markdown_files"] = len(markdown)
    report.check("fences, frontmatter e links Markdown")


def validate_tasks_and_status(parsed: dict[Path, Any], report: Report) -> None:
    task_re = re.compile(r"^###\s+(P\d{2}-T\d{2})\s+—\s+(.+)$", re.MULTILINE)
    owners: dict[str, set[str]] = defaultdict(set)
    for path in (ROOT / "phases").glob("p*.md"):
        for task_id, _title in task_re.findall(path.read_text(encoding="utf-8")):
            owners[task_id].add(path.name)
    for task_id, files in owners.items():
        if len(files) > 1:
            report.error(f"Task {task_id} aparece em múltiplas fases: {sorted(files)}")
    report.stats["tasks"] = len(owners)

    status = parsed.get(ROOT / "implementation-status.json")
    expected = [f"P{i:02d}" for i in range(13)]
    if isinstance(status, dict):
        actual = [phase.get("id") for phase in status.get("phases", [])]
        if actual != expected:
            report.error(f"Status possui fases {actual}; esperado {expected}")
        active = status.get("active_phase")
        by_id = {phase.get("id"): phase for phase in status.get("phases", [])}
        if active not in by_id:
            report.error(f"active_phase desconhecida: {active}")
    report.check("IDs de tasks e checkpoint das fases")


def validate_catalogs(parsed: dict[Path, Any], report: Report) -> None:
    tools_doc = parsed.get(ROOT / "contracts/mcp-tools.yaml")
    matrix = parsed.get(ROOT / "contracts/capability-release-matrix.yaml")
    if not isinstance(tools_doc, dict) or not isinstance(matrix, dict):
        return

    tools = [item.get("name") for item in tools_doc.get("tools", [])]
    duplicates = [name for name, count in Counter(tools).items() if count > 1]
    if duplicates:
        report.error(f"Tools duplicadas: {duplicates}")
    matrix_tools = [item.get("name") for item in matrix.get("tools", [])]
    unknown = sorted(set(matrix_tools) - set(tools))
    missing = sorted(set(tools) - set(matrix_tools))
    if unknown:
        report.error(f"Release matrix referencia tools desconhecidas: {unknown}")
    if missing:
        report.error(f"Tools sem fase de release: {missing}")

    phase_order = [f"P{i:02d}" for i in range(13)]
    for item in matrix.get("tools", []):
        if item.get("introduced") not in phase_order:
            report.error(f"Tool {item.get('name')} tem fase inválida {item.get('introduced')}")

    skill_files = {p.parent.name for p in (ROOT / "plugin-blueprint/skill-library").glob("*/SKILL.md")}
    matrix_skills = {item.get("name") for item in matrix.get("skills", [])}
    if skill_files != matrix_skills:
        report.error(f"Skills blueprint/matrix divergem: blueprint={sorted(skill_files)} matrix={sorted(matrix_skills)}")
    for item in matrix.get("skills", []):
        unknown_tools = sorted(set(item.get("required_tools", [])) - set(tools))
        if unknown_tools:
            report.error(f"Skill {item.get('name')} referencia tools desconhecidas: {unknown_tools}")
    report.stats["mcp_tools"] = len(tools)
    report.stats["skills"] = len(skill_files)
    report.check("catálogo de tools, Skills e matriz de release")


def validate_plugin_manifest(parsed: dict[Path, Any], report: Report) -> None:
    path = ROOT / "plugin-blueprint/.codex-plugin/plugin.json"
    manifest = parsed.get(path)
    if not isinstance(manifest, dict):
        return
    for key in ("name", "version", "description", "skills"):
        if key not in manifest:
            report.error(f"plugin.json sem campo {key}")

    skills = manifest.get("skills")
    active_dir: Path | None = None
    if isinstance(skills, str):
        if not skills.startswith("./"):
            report.error("plugin.json skills deve usar path relativo iniciado por ./")
        active_dir = (ROOT / "plugin-blueprint" / skills).resolve()
        try:
            active_dir.relative_to((ROOT / "plugin-blueprint").resolve())
        except ValueError:
            report.error("plugin.json skills sai da raiz do plugin")
        if not active_dir.is_dir():
            report.error("plugin.json aponta para diretório de Skills inexistente")
        elif not list(active_dir.glob("*/SKILL.md")):
            report.error("plugin.json não possui Skill ativa no diretório indicado")

    if manifest.get("version") != "0.0.0-spike":
        report.error("manifesto do blueprint deve permanecer na release segura 0.0.0-spike")
    if "apps" in manifest:
        report.error("manifesto do blueprint não deve conter apps antes da conexão MCP real")
    capabilities = manifest.get("interface", {}).get("capabilities", [])
    if "Write" in capabilities:
        report.error("manifesto P00 não pode anunciar capability Write")
    if skills != "./release-skills/p00/":
        report.error("manifesto P00 deve apontar somente para ./release-skills/p00/")

    report.check("manifest P00 seguro e Skills alvo isolados")


def validate_examples_domain(report: Report) -> None:
    path = ROOT / "examples/workout-technique-1600m-20m.json"
    data = load_json(path, report)
    if not isinstance(data, dict):
        return
    pool = data.get("pool_length_m")
    total_distance = 0

    def walk(nodes: list[dict[str, Any]], multiplier: int = 1) -> None:
        nonlocal total_distance
        for node in nodes:
            if node.get("type") == "step":
                end = node.get("end_condition", {})
                if end.get("type") == "distance":
                    meters = int(end.get("meters", 0))
                    if not isinstance(pool, int) or meters % pool:
                        report.error(f"Exemplo contém etapa {meters} m incompatível com piscina {pool} m")
                    total_distance += meters * multiplier
            elif node.get("type") == "repeat":
                walk(node.get("children", []), multiplier * int(node.get("repetitions", 1)))

    walk(data.get("nodes", []))
    if total_distance != 1600:
        report.error(f"Treino exemplo deveria totalizar 1600 m; total calculado={total_distance}")
    report.stats["example_workout_distance_m"] = total_distance
    report.check("invariantes de domínio do treino exemplo")


def write_report(report: Report) -> None:
    total_files = len(repository_files())
    total_lines = 0
    total_words = 0
    for path in repository_files("*.md"):
        text = path.read_text(encoding="utf-8")
        total_lines += len(text.splitlines())
        total_words += len(text.split())
    report.stats.update({"total_files": total_files, "markdown_lines": total_lines, "markdown_words": total_words})

    lines = [
        "# Relatório de validação do plano",
        "",
        f"> Gerado em UTC: `{datetime.now(timezone.utc).isoformat()}`",
        "",
        "## Resultado",
        "",
        f"- erros: **{len(report.errors)}**",
        f"- avisos: **{len(report.warnings)}**",
        f"- checks concluídos: **{len(report.checks)}**",
        "",
        "## Estatísticas",
        "",
    ]
    for key, value in sorted(report.stats.items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Checks", ""])
    lines.extend(f"- [x] {item}" for item in report.checks)
    lines.extend(["", "## Avisos", ""])
    lines.extend((f"- {item}" for item in report.warnings),)
    if not report.warnings:
        lines.append("- nenhum")
    lines.extend(["", "## Erros", ""])
    lines.extend((f"- {item}" for item in report.errors),)
    if not report.errors:
        lines.append("- nenhum")
    lines.extend([
        "",
        "## Nota",
        "",
        "Este relatório valida a consistência interna do pacote. Spikes P00 continuam obrigatórios porque disponibilidade de superfície, conexão, OAuth e comportamento Garmin precisam ser comprovados no ambiente real.",
        "",
    ])
    (ROOT / "PLAN_VALIDATION_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()

    report = Report()
    validate_required_structure(report)
    parsed = validate_json_yaml(report)
    validate_schemas(parsed, report)
    validate_markdown(report)
    validate_tasks_and_status(parsed, report)
    validate_catalogs(parsed, report)
    validate_plugin_manifest(parsed, report)
    validate_examples_domain(report)

    if args.write_report:
        write_report(report)

    print(f"checks={len(report.checks)} warnings={len(report.warnings)} errors={len(report.errors)}")
    for warning in report.warnings:
        print(f"WARN: {warning}")
    for error in report.errors:
        print(f"ERROR: {error}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
