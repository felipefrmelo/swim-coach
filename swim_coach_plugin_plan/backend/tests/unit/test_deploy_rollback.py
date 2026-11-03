"""Exercise a failed rollout against simulated infrastructure, preserving state."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

FAKE_INFRASTRUCTURE = """#!/usr/bin/env python3
import os, sys
from pathlib import Path
root = Path(os.environ["SIMULATED_RELEASE"])
args = sys.argv[1:]
name = Path(sys.argv[0]).name
with (root / "operations").open("a") as log:
    log.write(name + " " + " ".join(args) + "\\n")
if name == "df":
    print("Filesystem 1024-blocks Used Available Capacity Mounted")
    print("synthetic 10000000 0 10000000 0% /")
elif name == "git" and args[:1] == ["rev-parse"]:
    print("b" * 40)
elif name == "docker":
    if "psql" in args:
        print((root / "schema").read_text().strip())
    elif "pg_dump" in args:
        print("synthetic-backup")
    elif "downgrade" in args:
        if os.environ["REFUSE_SCHEMA_ROLLBACK"] == "true":
            sys.exit(1)
        (root / "schema").write_text("000017")
    elif "migrate" in args and "run" in args and "alembic" not in args:
        (root / "schema").write_text("000018")
    elif "up" in args and "--wait" in args:
        marker = root / "first_start_failed"
        if not marker.exists():
            marker.touch()
            sys.exit(1)
        (root / "restored_application").touch()
    elif "inspect" in args and "--format" in args:
        print("synthetic-image")
    elif "ps" in args and "-q" in args:
        print("synthetic-container")
"""


@pytest.mark.parametrize("refuse", [False, True])
def test_failed_release_restores_compatible_schema_or_preserves_new_data(tmp_path, refuse) -> None:
    repository = tmp_path / "repository"
    (repository / "swim_coach_plugin_plan").mkdir(parents=True)
    (repository / ".deployed-commit").write_text("a" * 40)
    (tmp_path / "schema").write_text("000017")
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    for name in ("git", "docker", "df", "curl"):
        executable = tools_dir / name
        executable.write_text(FAKE_INFRASTRUCTURE)
        executable.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{tools_dir}:{os.environ['PATH']}",
        "SIMULATED_RELEASE": str(tmp_path),
        "REFUSE_SCHEMA_ROLLBACK": str(refuse).lower(),
        "SWIM_COACH_DEPLOY_ROOT": str(repository),
    }
    result = subprocess.run(  # noqa: S603 - fixed repository script and synthetic arguments
        ["/bin/bash", str(ROOT / "ops/deploy-vm.sh"), "b" * 40],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert (tmp_path / "schema").read_text() == ("000018" if refuse else "000017")
    assert (tmp_path / "restored_application").exists() is not refuse
    operations = (tmp_path / "operations").read_text()
    assert "pg_restore -l" in operations
    assert "downgrade 000017" in operations
    assert (repository / ".deployed-commit").read_text() == "a" * 40
    if refuse:
        assert "preserve new data" in result.stderr
