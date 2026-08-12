# P10 — adaptive weekly planning evidence

State: implementation and automated gate complete; human review with real
athlete-owned data in ChatGPT pending.

Publication: commit `543e3f9`, draft PR #11, based on `p09-mcp-apps-ui`.

## Implemented

- immutable `TrainingRuleSet` records include semantic version, effective range,
  canonical JSON and SHA-256 content hash;
- `PlanningRun` persists a deterministic snapshot of the owned goal, pool,
  availability, constraints, recent adherence/activities/feedback and current
  week, plus input/output hashes;
- the pure week generator caps the week at three sessions and 8% progression,
  respects pool multiples and duration, preserves technique, verifies 36-hour
  hard-session spacing, reduces load for pain/high RPE/low adherence and emits a
  cyclic recovery week;
- missed sessions are never rolled forward automatically. Proposed date changes
  are recorded as review-only decisions and do not mutate the calendar;
- ordered `TrainingDecision` records retain rule ID, bounded evidence references,
  before/after values and rationale;
- `propose_week_plan` requires `planning:write proposals:write`, returns an exact
  `ActionProposal`, and never approves, creates workouts, schedules, executes or
  calls Garmin;
- goal progress now separates endurance, pace, consistency and confidence while
  retaining sample size and quality;
- plugin candidate `0.4.0` adds the validated `plan-swim-week` Skill and 22 new
  evals, for 154 total cases across seven Skills.

## Automated evidence

- final `make check` passed with 117 Python tests, 2 Vitest tests, Ruff, mypy,
  ESLint, TypeScript and both repository validators (`8` checks, no warnings or
  errors);
- focused domain tests include a fixed golden output hash
  `e31028ff8982cef8ba488e67ef93bf7b6e21e0f857cabe21b840e31f8d0b039c`
  and 40 Hypothesis examples over availability, duration and adherence;
- the golden week for 2026-08-17 contains 1,700 m technique, 1,700 m endurance
  and 1,700 m controlled threshold sessions on Monday, Wednesday and Saturday;
- PostgreSQL 16 Testcontainers applied migration `000008` in `up → down → up`;
- the integration test invoked the real MCP Streamable HTTP server/client, checked
  the closed nested constraints schema, P10 capability/version, ownership and
  scopes, then replayed the same canonical input into exactly one planning run,
  proposal and ordered decision trace;
- approval of the exact proposal hash changed only proposal state: planned-workout
  and workout-schedule row counts remained unchanged and external effects were
  empty;
- an unrelated authenticated user received `RESOURCE_NOT_FOUND` for the proposal.
- `make dependency-scan` found no known Python or pnpm vulnerabilities;
- `make secret-scan` inspected 27 commits and the final directory with no leaks;
- `make build` completed the Vite production bundle and all four Compose images.
- GitHub Actions run `31614812787` passed the `quality` job in 1m41s, including
  tests, scans and container builds from a clean checkout.

## Security and privacy evidence

- the feature is disabled by default and requires the OAuth-controlled write
  surface;
- free-form planning notes are not persisted in the deterministic snapshot; only
  a boolean `user_notes_present` signal is retained;
- proposal payloads contain owned internal IDs and bounded plan data, not Garmin
  credentials, provider IDs, FIT bytes or tokens;
- pain is treated only as a conservative safety signal and never as diagnosis;
- no code path executes or publishes a planning proposal in P10.

## Evidence boundary and pending real gate

The PostgreSQL and MCP tests use real protocol/database components with sanitized
fixture identities. They do not prove that a week generated from the user's real
Garmin history is useful. P10 therefore remains `IN_PROGRESS` until:

1. real Garmin activities are persisted through the earlier P02/P03 gate;
2. ChatGPT invokes `plan-swim-week` for an owned future Monday;
3. the user reviews session dates, volume, warnings and every material decision;
4. a sanitized transcript retains only the planning run ID prefix, ruleset
   version/hash prefix, output hash prefix and the human accept/revise outcome;
5. row counts or a follow-up read confirm the proposal did not silently create,
   schedule, approve, execute or publish workouts.
