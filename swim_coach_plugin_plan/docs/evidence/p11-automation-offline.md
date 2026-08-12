# P11 — automation and offline resilience evidence

State: implementation and automated gate complete; personal automated cycle,
offline iPhone screenshot and live queue screenshot pending.

## Implemented

- timezone-aware scheduler scans active users at most once per minute and creates
  daily Garmin sync and weekly planning jobs with stable keys;
- the planning worker calls the deterministic P10 service and only persists a
  review proposal. It never approves, creates workouts, schedules or publishes;
- imported activities already queue `activity.fetch_file`, whose existing replay-
  safe service performs download, normalize, match and analysis;
- deduplicated in-app notifications cover upcoming workouts, pending feedback,
  terminal automation failures and weekly proposals ready for review;
- migration `000009` adds user-owned notification persistence and indexes;
- `/api/v1/operations` exposes redacted queue age/status metrics, notifications
  and safe retry. Retry independently verifies ownership, classification,
  ambiguity and idempotency;
- finished-job retention is bounded and leaves audit/outbox evidence untouched;
- the PWA caches only its shell/assets and workout GET read model, marks cached
  workout data stale, and explicitly excludes actions, proposals, approval,
  rejection, publication and scheduling;
- feedback uses IndexedDB with a stable idempotency key, visible queued state and
  online reconciliation. The server hashes the canonical payload and rejects key
  reuse with different content;
- the operations screen provides queue metrics, notification inbox and retry only
  for failures declared safe.

## Automated evidence

- `make check` passed Ruff, ESLint, mypy, TypeScript, 118 Python tests, four
  Vitest tests and both repository validators;
- 20 PostgreSQL/Testcontainers integration tests passed after adding P11 coverage;
- migration head `000009` completed `up → down → up` on PostgreSQL 16;
- scheduler unit evidence fixes Sunday 18:00 in `America/Sao_Paulo`, materializes
  sync plus next-Monday planning exactly once, and repeats with zero duplicates;
- integration evidence creates the same notification twice and persists one row,
  measures terminal metrics and purges only an old finished job;
- the existing activity pipeline integration replays processing while retaining
  one current normalization/match and owned feedback/analysis versions;
- service-worker policy tests verify the narrow workout GET allowlist, stale marker
  and every controlled-action exclusion;
- `make build` produced the Vite bundle and API, worker, migration and web images.

## Security boundary

- automation is disabled by default; sync/planning jobs are only registered when
  their underlying runtime services are enabled;
- browser storage contains feedback payload plus internal activity ID and
  idempotency key, never cookies, bearer tokens, Garmin credentials or FIT bytes;
- cached reads cannot satisfy a write because non-GET requests are ignored and
  every action boundary is excluded from cache;
- error payloads shown by operations are redacted stable codes, not raw exceptions;
- generic reminder text avoids sensitive workout or health details.

## Pending real gate

P11 remains `IN_PROGRESS` until the personal environment supplies these three
sanitized proofs:

1. enable automation for one bounded cycle and show one imported activity reaches
   normalized/analyzed/matched state without duplicate jobs;
2. on an iPhone-sized installed PWA, load a workout, go offline, capture the stale
   banner, queue feedback, reconnect and confirm exactly one server feedback row;
3. capture `/operations` with queue age returning to zero, one deduplicated notice
   and no expired/offline approval or external Garmin effect.
