UV_CACHE_DIR ?= /tmp/swim-coach-uv-cache
PNPM_STORE_DIR ?= /tmp/swim-coach-pnpm-store
GIT_ROOT := $(shell git rev-parse --show-toplevel)

.PHONY: bootstrap build check dependency-scan dev down format-check lint secret-scan test typecheck validate

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

validate:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python tools/validate_repository.py
	python3 tools/validate_plan.py

build:
	corepack pnpm build
	docker compose build

check: format-check lint typecheck test validate

dependency-scan:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run pip-audit --cache-dir /tmp/swim-coach-pip-audit-cache
	corepack pnpm audit --audit-level high

secret-scan:
	docker run --rm -v $(GIT_ROOT):/repo ghcr.io/gitleaks/gitleaks:v8.28.0 git /repo --no-banner --config /repo/swim_coach_plugin_plan/.gitleaks.toml
	docker run --rm -v $(GIT_ROOT):/repo ghcr.io/gitleaks/gitleaks:v8.28.0 dir /repo --no-banner --config /repo/swim_coach_plugin_plan/.gitleaks.toml

dev:
	docker compose up --build

down:
	docker compose down
