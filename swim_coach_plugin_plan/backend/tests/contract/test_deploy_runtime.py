from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_backend_runtime_files_are_owned_by_the_unprivileged_user() -> None:
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text()

    assert "COPY --chown=swim-coach:swim-coach backend/src ./backend/src" in dockerfile
    assert (
        "COPY --chown=swim-coach:swim-coach backend/alembic.ini ./backend/alembic.ini" in dockerfile
    )
    assert "COPY --chown=swim-coach:swim-coach backend/alembic ./backend/alembic" in dockerfile


def test_deploy_preflights_the_new_migration_image_before_stopping_services() -> None:
    deploy_script = (ROOT / "ops" / "deploy-vm.sh").read_text()

    preflight = "compose run --rm migrate alembic -c backend/alembic.ini current"
    assert preflight in deploy_script
    assert deploy_script.index(preflight) < deploy_script.index("services_stopped=true")
