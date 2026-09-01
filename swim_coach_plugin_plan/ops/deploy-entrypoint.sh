#!/usr/bin/env bash
set -Eeuo pipefail

repository_root="${SWIM_COACH_DEPLOY_ROOT:-/opt/swim-coach}"
deploy_script_path="swim_coach_plugin_plan/ops/deploy-vm.sh"

if [[ -n "${SSH_ORIGINAL_COMMAND:-}" ]]; then
  if [[ "${SSH_ORIGINAL_COMMAND}" =~ ^deploy[[:space:]]([0-9a-f]{40})$ ]]; then
    target_commit="${BASH_REMATCH[1]}"
  else
    echo "Deploy refused: invalid SSH command." >&2
    exit 1
  fi
else
  target_commit="${1:-}"
  if [[ ! "${target_commit}" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Usage: $0 <40-character-main-commit>" >&2
    exit 1
  fi
fi

cd "${repository_root}"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Deploy refused: tracked files contain local changes." >&2
  git status --short >&2
  exit 1
fi

git fetch origin main
main_commit="$(git rev-parse origin/main)"
if [[ "${target_commit}" != "${main_commit}" ]]; then
  echo "Deploy refused: ${target_commit} is not the current origin/main (${main_commit})." >&2
  exit 1
fi

temporary_script="$(mktemp /tmp/swim-coach-deploy.XXXXXX)"
cleanup() {
  rm -f "${temporary_script}"
}
trap cleanup EXIT

git show "${target_commit}:${deploy_script_path}" > "${temporary_script}"
chmod 700 "${temporary_script}"
SWIM_COACH_DEPLOY_ROOT="${repository_root}" bash "${temporary_script}" "${target_commit}"
