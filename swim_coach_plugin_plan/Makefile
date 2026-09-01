UV_CACHE_DIR ?= /tmp/swim-coach-uv-cache
PNPM_STORE_DIR ?= /tmp/swim-coach-pnpm-store
GIT_ROOT := $(shell git rev-parse --show-toplevel)

.PHONY: bootstrap build check dependency-scan deploy-check dev down e2e format-check image-scan lint load-smoke sbom secret-scan security-scan test typecheck validate

bootstrap:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv sync --all-groups --frozen
	corepack pnpm install --frozen-lockfile --store-dir $(PNPM_STORE_DIR)

format-check:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run ruff format --check backend tools/validate_repository.py

lint:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run ruff check backend tools/validate_repository.py
	corepack pnpm lint

typecheck:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run mypy
	corepack pnpm check

test:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run pytest
	corepack pnpm test

e2e:
	corepack pnpm e2e

validate:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python tools/validate_repository.py

deploy-check:
	bash -n ops/deploy-entrypoint.sh ops/deploy-vm.sh

build:
	corepack pnpm build
	docker compose build

check: format-check lint typecheck test validate deploy-check

dependency-scan:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run pip-audit --cache-dir /tmp/swim-coach-pip-audit-cache
	corepack pnpm audit --audit-level high

secret-scan:
	docker run --rm -v $(GIT_ROOT):/repo ghcr.io/gitleaks/gitleaks:v8.28.0 git /repo --no-banner --config /repo/swim_coach_plugin_plan/.gitleaks.toml
	docker run --rm -v $(GIT_ROOT):/repo ghcr.io/gitleaks/gitleaks:v8.28.0 dir /repo --no-banner --config /repo/swim_coach_plugin_plan/.gitleaks.toml

sbom:
	docker run --rm -v $(CURDIR):/repo -v /tmp:/out anchore/syft:v1.33.0 dir:/repo -o cyclonedx-json=/out/swim-coach-1.0.0.cdx.json

image-scan:
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v /tmp/swim-coach-trivy-cache:/root/.cache/trivy aquasec/trivy:0.66.0 image --scanners vuln --exit-code 1 --severity HIGH,CRITICAL swim-coach-api:latest
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v /tmp/swim-coach-trivy-cache:/root/.cache/trivy aquasec/trivy:0.66.0 image --scanners vuln --exit-code 1 --severity HIGH,CRITICAL swim-coach-worker:latest
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v /tmp/swim-coach-trivy-cache:/root/.cache/trivy aquasec/trivy:0.66.0 image --scanners vuln --exit-code 1 --severity HIGH,CRITICAL swim-coach-migrate:latest
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v /tmp/swim-coach-trivy-cache:/root/.cache/trivy aquasec/trivy:0.66.0 image --scanners vuln --exit-code 1 --severity HIGH,CRITICAL swim-coach-web:latest

security-scan: dependency-scan secret-scan sbom image-scan

load-smoke:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python backend/scripts/load_smoke.py

dev:
	docker compose up --build

down:
	docker compose down
