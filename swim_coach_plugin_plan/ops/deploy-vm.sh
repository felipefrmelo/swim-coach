#!/usr/bin/env bash
set -Eeuo pipefail

repository_root="${SWIM_COACH_DEPLOY_ROOT:-/opt/swim-coach}"
application_root="${repository_root}/swim_coach_plugin_plan"
compose_project="swim-coach-production"
marker_path="${repository_root}/.deployed-commit"
backup_root="${repository_root}/backups"
lock_path="${repository_root}/.deploy.lock"
minimum_free_kb=2097152
cleanup_threshold_kb=2621440
target_commit="${1:-}"
compose_files=(
  -f docker-compose.yml
  -f docker-compose.production.yml
  -f docker-compose.vm.yml
)
services=(api worker web)
services_stopped=false
deployment_succeeded=false
current_deployed=""

compose() {
  docker compose -p "${compose_project}" "${compose_files[@]}" "$@"
}

available_disk_kb() {
  df -Pk "${repository_root}" | awk 'NR == 2 { print $4 }'
}

rollback_application() {
  local status=$?
  trap - ERR INT TERM

  if [[ "${services_stopped}" == "true" && "${deployment_succeeded}" != "true" ]]; then
    echo "Deployment failed after services stopped; attempting application rollback." >&2
    cd "${application_root}"
    for service in "${services[@]}"; do
      rollback_ref="swim-coach-rollback-${service}:${current_deployed}"
      if docker image inspect "${rollback_ref}" > /dev/null 2>&1; then
        docker image tag "${rollback_ref}" "${compose_project}-${service}:latest" || true
      fi
    done
    compose up -d --no-deps --no-build --force-recreate --wait api worker web || true
  fi

  exit "${status}"
}
trap rollback_application ERR INT TERM

if [[ ! "${target_commit}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Deploy refused: target must be a full 40-character commit SHA." >&2
  exit 1
fi

exec {deploy_lock_fd}> "${lock_path}"
if ! flock -n "${deploy_lock_fd}"; then
  echo "Deploy refused: another production deployment is running." >&2
  exit 1
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
  echo "Deploy refused: ${target_commit} is not current origin/main (${main_commit})." >&2
  exit 1
fi

if [[ -f "${marker_path}" ]]; then
  current_deployed="$(< "${marker_path}")"
else
  current_deployed="$(git rev-parse HEAD)"
fi
if [[ ! "${current_deployed}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Deploy refused: invalid deployed commit marker." >&2
  exit 1
fi
if ! git merge-base --is-ancestor "${current_deployed}" "${target_commit}"; then
  echo "Deploy refused: target is not a fast-forward of ${current_deployed}." >&2
  exit 1
fi

if [[ "${current_deployed}" == "${target_commit}" ]] \
  && curl --fail --silent --show-error http://127.0.0.1:18000/health/ready > /dev/null \
  && curl --fail --silent --show-error http://127.0.0.1:14173/health > /dev/null; then
  echo "Already deployed and healthy at ${target_commit}."
  deployment_succeeded=true
  exit 0
fi

free_kb="$(available_disk_kb)"
if (( free_kb < cleanup_threshold_kb )); then
  echo "Low disk space (${free_kb} KiB free); pruning only dangling images and build cache older than 72h."
  docker image prune -f
  docker builder prune -f --filter until=72h
  free_kb="$(available_disk_kb)"
fi
if (( free_kb < minimum_free_kb )); then
  echo "Deploy refused: ${free_kb} KiB free after safe cleanup; ${minimum_free_kb} KiB required." >&2
  exit 1
fi

cd "${application_root}"
mkdir -p "${backup_root}"
umask 077
backup_path="${backup_root}/predeploy-$(date -u +%Y%m%dT%H%M%SZ).dump"
compose exec -T postgres pg_dump -U swim_coach -d swim_coach -Fc > "${backup_path}"
chmod 600 "${backup_path}"
if ! compose exec -T postgres pg_restore -l < "${backup_path}" > /dev/null; then
  rm -f "${backup_path}"
  echo "Deploy refused: pre-deploy backup verification failed." >&2
  exit 1
fi

for service in "${services[@]}"; do
  container_id="$(compose ps -q "${service}")"
  if [[ -n "${container_id}" ]]; then
    image_id="$(docker inspect --format '{{.Image}}' "${container_id}")"
    docker image tag "${image_id}" "swim-coach-rollback-${service}:${current_deployed}"
  fi
done

cd "${repository_root}"
git merge --ff-only "${target_commit}"

cd "${application_root}"
compose config --quiet
compose build api worker migrate web

services_stopped=true
compose stop worker
compose stop api web
compose run --rm migrate
compose up -d --no-deps --no-build --wait api worker web

curl --fail --silent --show-error http://127.0.0.1:18000/health/ready
echo
curl --fail --silent --show-error http://127.0.0.1:14173/health > /dev/null

marker_tmp="$(mktemp "${marker_path}.XXXXXX")"
printf '%s\n' "${target_commit}" > "${marker_tmp}"
chmod 600 "${marker_tmp}"
mv "${marker_tmp}" "${marker_path}"

mapfile -t expired_backups < <(
  find "${backup_root}" -maxdepth 1 -type f -name 'predeploy-*.dump' -printf '%T@ %p\n' \
    | sort -nr \
    | tail -n +8 \
    | cut -d' ' -f2-
)
for expired_backup in "${expired_backups[@]}"; do
  rm -f -- "${expired_backup}"
done

for service in "${services[@]}"; do
  retained_ref="swim-coach-rollback-${service}:${current_deployed}"
  while IFS= read -r rollback_ref; do
    if [[ -n "${rollback_ref}" && "${rollback_ref}" != "${retained_ref}" ]]; then
      docker image rm "${rollback_ref}" > /dev/null || true
    fi
  done < <(docker image ls --format '{{.Repository}}:{{.Tag}}' "swim-coach-rollback-${service}")
done
docker builder prune -f --filter until=168h > /dev/null || true

services_stopped=false
deployment_succeeded=true
trap - ERR INT TERM
echo "Deployment completed from ${target_commit}."
