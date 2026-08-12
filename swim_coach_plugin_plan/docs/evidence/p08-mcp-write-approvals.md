# P08 — MCP controlled write evidence

State: local implementation and automated gate complete; real host/Garmin gate pending.

Publication: commit `ee728f0`, draft PR #9, based on `p06-plugin-read-only`.

CI run `31608025063` exposed an outdated `FailingGarminSync` test double after
the real service gained `from_date`/`force`; production code and the other 98
tests passed. Commit `c12e85a` aligned the fake with the service contract, and
the focused retry/lease integration passed 2/2 locally.

## Implemented

- independent `SWIM_COACH_MCP_WRITE_ENABLED` kill switch, which requires a
  complete OAuth issuer/resource pair;
- 12 P08 tools with closed input schemas, granular scopes, ownership and risk
  annotations matching `contracts/mcp-tools.yaml`;
- exact proposal hash and expiry, approval without execution, and execution in
  a separate transaction with a dynamic action scope;
- idempotent Garmin sync, feedback write, publication execution and safe job
  retry; ambiguous external effects are never retried;
- local workout draft plus reviewable change/reschedule proposals without
  silently applying either proposal;
- migration `000007` linking sanitized invocation records to a correlation and
  causation entity while keeping arguments as SHA-256 only;
- plugin `0.2.0` with six Skills and a literal hard-turn boundary in
  `publish-to-garmin`;
- 132 contract eval cases, 22 per Skill across direct, indirect, follow-up,
  empty, auth and adversarial categories.

## Automated evidence

- an integral `make check` passed with 99 Python and 2 web tests before the
  final concurrency/recovery hardening;
- on the final tree: Ruff, mypy (86 source files), ESLint and TypeScript passed;
- on the final tree: 81 unit/property/contract/plan tests and 2 web tests passed;
- on the final tree: 7 changed-area PostgreSQL tests passed for MCP write,
  Garmin publication, sync and worker behavior;
- PostgreSQL/Testcontainers integration:
  - tampered hash rejected;
  - execution before approval rejected;
  - approval returns `APPROVED` and no execution;
  - missing dynamic `garmin:publish` scope rejected;
  - other-user proposal returns not found;
  - two execution calls create exactly one approval, one execution and one job;
  - concurrent execution calls serialize and return the same execution;
  - safe failed retry is atomic/idempotent and ambiguous effects are rejected;
- P07 REST compatibility retained: one explicit PWA approval request performs
  approval then execution, and the fake provider reconciliation test remains green;
- all six Skills passed the official quick validator and the plugin passed the
  plugin creator validator.
- dependency audits reported no known vulnerabilities; gitleaks scanned history
  and the final directory without findings.

Two attempts to repeat the monolithic `make check` after the final hardening
expired in the environment's automatic Docker permission review before the
command started. The final-tree gate was therefore decomposed into the
non-Docker suite and the changed-area PostgreSQL suite above; no test failure was
hidden or waived.

## Real evidence already supplied, but not sufficient for this gate

- Garmin read probe: 2 devices, 20 recent activities and 6 pool swims, with no
  external write;
- Secure MCP Tunnel doctor: target reachable and ChatGPT invoked P00
  `get_capabilities` successfully;
- Auth0 discovery: authorization code, PKCE S256 and DCR supported.

These prove P00 connectivity/read viability. They do not prove a P08 write from
the `0.2.0` Skill surface.

## Pending real gate

1. install/upgrade the personal copy to `0.2.0` and start a new conversation;
2. authenticate the connector with the P08 scopes;
3. preview a disposable `[CANARY]` workout in one user turn;
4. confirm the exact displayed hash in a later user turn;
5. observe one job/binding and exactly one Garmin workout/calendar entry;
6. replay execution and prove that no duplicate is created;
7. retain only a sanitized transcript, IDs/hashes truncated, with no token,
   credential, FIT file or personal provider identifier.

Until those steps pass, P08 remains `IN_PROGRESS`.
