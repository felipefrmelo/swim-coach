from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from swim_coach.infrastructure.backup import create_backup, prune_backups, restore_backup


def test_encrypted_backup_restore_verifies_database_and_artifacts(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "owned.fit").write_bytes(b"sanitized-fit")
    backup = tmp_path / "backup.scbk"
    restored = tmp_path / "restored"
    commands: list[list[str]] = []

    def runner(command: list[str] | tuple[str, ...]) -> None:
        values = list(command)
        commands.append(values)
        if values[0] == "pg_dump":
            Path(values[values.index("--file") + 1]).write_bytes(b"postgres-custom-dump")

    key = bytes(range(32))
    manifest = create_backup("postgresql://isolated/source", artifacts, backup, key, runner=runner)
    restored_manifest = restore_backup(
        backup,
        "postgresql://isolated/restore",
        restored,
        key,
        runner=runner,
    )

    assert backup.stat().st_mode & 0o777 == 0o600
    assert manifest == restored_manifest
    assert (restored / "owned.fit").read_bytes() == b"sanitized-fit"
    assert [command[0] for command in commands] == ["pg_dump", "pg_restore"]


def test_backup_tampering_and_nonempty_restore_fail_closed(tmp_path: Path) -> None:
    backup = tmp_path / "backup.scbk"

    def runner(command: list[str] | tuple[str, ...]) -> None:
        values = list(command)
        if values[0] == "pg_dump":
            Path(values[values.index("--file") + 1]).write_bytes(b"dump")

    key = bytes(range(32))
    create_backup("postgresql://isolated/source", tmp_path / "missing", backup, key, runner=runner)
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep").write_text("do not overwrite")
    with pytest.raises(ValueError, match="must be empty"):
        restore_backup(backup, "postgresql://isolated/restore", target, key, runner=runner)

    damaged = bytearray(backup.read_bytes())
    damaged[-1] ^= 1
    backup.write_bytes(damaged)
    with pytest.raises(InvalidTag):
        restore_backup(
            backup,
            "postgresql://isolated/restore",
            tmp_path / "clean",
            key,
            runner=runner,
        )


def test_backup_retention_only_removes_old_envelopes(tmp_path: Path) -> None:
    backups = [tmp_path / f"backup-{index}.scbk" for index in range(4)]
    for index, path in enumerate(backups):
        path.write_bytes(str(index).encode())
        path.touch()
    unrelated = tmp_path / "do-not-delete.txt"
    unrelated.write_text("safe")

    removed = prune_backups(tmp_path, retain=2, protected=backups[-1])

    assert backups[-1].exists()
    assert unrelated.exists()
    assert len(removed) == 2
    assert sum(path.exists() for path in backups) == 2
