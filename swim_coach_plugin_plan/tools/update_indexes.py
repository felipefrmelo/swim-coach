#!/usr/bin/env python3
"""Regenerate FILE_INDEX.md and TASK_INDEX.md from the plan tree."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

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
TASK_RE = re.compile(r"^###\s+(P\d{2}-T\d{2})\s+—\s+(.+)$", re.MULTILINE)


def first_heading(path: Path) -> str:
    if path.suffix.lower() == ".md":
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    return "arquivo estruturado/auxiliar"


def write_task_index() -> None:
    rows: list[tuple[str, str, str, str]] = []
    for phase_path in sorted((ROOT / "phases").glob("p*.md")):
        phase_text = phase_path.read_text(encoding="utf-8")
        phase_title = first_heading(phase_path)
        for task_id, title in TASK_RE.findall(phase_text):
            rows.append((task_id, phase_title, title, phase_path.relative_to(ROOT).as_posix()))

    lines = [
        "# Índice de tasks",
        "",
        "Gerado de `phases/pXX-*.md`. O arquivo da fase continua sendo a fonte de aceite, testes, evidências e gate.",
        "",
        f"**Total:** {len(rows)} tasks.",
        "",
        "| Task | Fase | Título | Especificação |",
        "|---|---|---|---|",
    ]
    for task_id, phase_title, title, rel in rows:
        lines.append(f"| `{task_id}` | {phase_title.split('—', 1)[0].strip()} | {title} | [`{rel}`]({rel}) |")
    lines.append("")
    (ROOT / "TASK_INDEX.md").write_text("\n".join(lines), encoding="utf-8")


def category(path: Path) -> str:
    rel = path.relative_to(ROOT)
    top = rel.parts[0]
    mapping = {
        "docs": "Documentos duráveis",
        "phases": "Fases",
        "prompts": "Prompts por fase",
        "contracts": "Contratos",
        "adrs": "ADRs",
        "plugin-blueprint": "Blueprint do plugin",
        "examples": "Exemplos",
        "evals": "Evals",
        "tools": "Ferramentas do plano",
    }
    return mapping.get(top, "Raiz e controle")


def write_file_index() -> None:
    excluded = {"FILE_INDEX.md", "CHECKSUMS.sha256"}
    files = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_DIRS for part in path.parts)
        and path.relative_to(ROOT).as_posix() not in excluded
    ]
    groups: dict[str, list[Path]] = {}
    for path in files:
        groups.setdefault(category(path), []).append(path)
    order = ["Raiz e controle", "Documentos duráveis", "Fases", "Prompts por fase", "Contratos", "ADRs", "Blueprint do plugin", "Exemplos", "Evals", "Ferramentas do plano"]
    lines = [
        "# Índice de arquivos",
        "",
        "Mapa gerado do pacote. Arquivos de código/contrato sem título Markdown usam uma descrição genérica; consulte o conteúdo para detalhes.",
        "",
    ]
    for group in order:
        paths = sorted(groups.get(group, []))
        if not paths:
            continue
        lines.extend([f"## {group}", "", "| Caminho | Finalidade/título |", "|---|---|"])
        for path in paths:
            rel = path.relative_to(ROOT).as_posix()
            title = first_heading(path)
            lines.append(f"| [`{rel}`]({rel}) | {title.replace('|', '\\|')} |")
        lines.append("")
    lines.append(f"**Total indexado:** {len(files)} arquivos (sem contar este índice e o arquivo de checksums).")
    lines.append("")
    (ROOT / "FILE_INDEX.md").write_text("\n".join(lines), encoding="utf-8")


def write_checksums() -> None:
    excluded = {"CHECKSUMS.sha256"}
    files = sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_DIRS for part in path.parts)
        and path.relative_to(ROOT).as_posix() not in excluded
    )
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
        f"./{path.relative_to(ROOT).as_posix()}"
        for path in files
    ]
    (ROOT / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_task_index()
    write_file_index()
    write_checksums()
    print("TASK_INDEX.md, FILE_INDEX.md e CHECKSUMS.sha256 atualizados")
