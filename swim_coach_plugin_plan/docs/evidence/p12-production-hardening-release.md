# P12 — hardening, privacy and personal release evidence

State: implementation and automated/integration gate complete; phase remains
`IN_PROGRESS` because P11 and earlier real-data gates are still open.

Publication: commit `aa98d80`, draft PR #13, based on
`p11-automation-offline`.

## Delivered by task

- **P12-T01:** API/worker/migrate run as UID 10001 and web as UID 101; production
  overlay adds read-only rootfs, cap-drop, no-new-privileges, tmpfs/resources,
  one-shot migration and loopback-only exposure behind managed HTTPS.
- **P12-T02/T03:** AES-256-GCM backup covers PostgreSQL custom dump plus object
  storage, embedded manifest/checksums, private key/output permissions, atomic
  creation, count retention and fail-closed extraction/restore.
- **P12-T04:** owned ZIP export contains structured JSON and verified FIT while
  excluding credentials. Deletion is idempotent, exact-phrase confirmed,
  cooling-off staged, revokes sessions/Garmin, cancels jobs/proposals, cascades
  user data and preserves a non-identifying tombstone.
- **P12-T05:** readiness verifies DB, migration `000010` and writable storage;
  operations exposes queue/dead-job metrics and `ops/alerts.yaml` defines health,
  queue, backup, disk and provider thresholds/runbooks.
- **P12-T06:** bounded body/rate controls, API/PWA security headers, threat-model
  delta, dependency/secret/SBOM/image scans and incident runbook were added.
- **P12-T07:** bounded REST/MCP transport smoke and capacity/retention limits were
  recorded; privacy tables and queue queries use ownership/status/time indexes.
- **P12-T08:** backend, PWA and canonical plugin are `1.0.0`; a hash/image/evidence
  manifest exists at `releases/plugin-1.0.0.json`.
- **P12-T09:** install/update/rollback/reconnect/backup/restore/incident operations
  are in `docs/runbooks/p12-operations.md`.
- **P12-T10:** public submission is explicitly denied by
  `docs/public-readiness.md` until its independent gates pass.

## Real integration evidence

- PostgreSQL 16 restore drill: encrypted `pg_dump` → isolated database
  `pg_restore`; migration `000010`, one user, one identity, one activity, one
  workout, login resolution and artifact bytes/checksum all matched. The complete
  test took **5.02 s** and destroyed only its randomly named target database.
- disposable Compose smoke: API/worker/migrate/web healthy; readiness reported
  database, schema and artifact storage ready. Load test issued **120** requests
  with concurrency **12**, p95 **82.35 ms** against a 500 ms gate; 80 responses
  were 200 and 40 MCP non-protocol GETs returned the expected 406.
- final images: API/worker/migrate use `swim-coach`; web uses UID 101. Trivy found
  **zero HIGH/CRITICAL** after changing Python to patched Alpine 3.23 and upgrading
  the nginx Alpine runtime. `pip-audit` and `pnpm audit` found zero known issues.
- Gitleaks scanned 32 commits and 4.73 MB of the worktree with zero leaks. Syft
  generated a 744-component CycloneDX SBOM at `/tmp`, SHA-256
  `449a3f29efa2e54037786d82c6cf6a69492c1a46ac3f76dac7ea09a46b56b97d`.
- canonical repository tests: **126 Python** and **4 Vitest** passed, plus Ruff,
  mypy, ESLint and TypeScript.
- GitHub Actions run `31621402450` passed the complete `quality` job, including
  static checks, tests, dependency/secret scans and all four container builds.
- personal Codex plugin was upgraded from `0.0.0-spike` to validated/enabled
  `1.0.0+codex.20260812170215`; the previous copy is recoverable at
  `/tmp/swim-coach-plugin-pre-p12`.

## User-supplied real proofs retained

- Garmin read probe: 2 devices, 20 recent activities, 6 pool swims, Forerunner
  family detected and `external_write_performed=false`; mobile login attempts
  received 429 but the final read probe passed.
- Secure MCP Tunnel doctor passed config, target reachability and UI; ChatGPT
  invoked `@coach` and correctly described the P00 capability boundary.
- Auth0 metadata probe passed Authorization Code, PKCE S256 and DCR without
  requesting or printing a token.

## Honest remaining gate

The 1.0.0 artifact is a hardened personal **release candidate**, not a public
release. A new ChatGPT/Codex thread must smoke the installed seven-Skill package,
and P11 still needs the personal automation/offline/queue evidence. Earlier
real-data gates listed in the release manifest also remain open; fixture/isolated
integration evidence does not replace them.
