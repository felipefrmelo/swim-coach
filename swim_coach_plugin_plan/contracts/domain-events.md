# Eventos de domínio e outbox

Envelope:

```json
{
  "event_id": "uuid",
  "event_type": "swim_coach.workouts.revision_approved.v1",
  "occurred_at": "2026-08-05T12:00:00Z",
  "aggregate_type": "PlannedWorkout",
  "aggregate_id": "uuid",
  "aggregate_version": 4,
  "user_id": "uuid",
  "correlation_id": "uuid",
  "causation_id": "uuid|null",
  "payload": {}
}
```

Catálogo inicial:

| Evento | Producer | Consumers |
|---|---|---|
| `athlete.profile_updated.v1` | athlete | planning cache/audit |
| `goals.goal_activated.v1` | goals | planning/progress |
| `goals.goal_updated.v1` | goals | planning/progress/audit |
| `workouts.draft_created.v1` | workouts | audit |
| `workouts.revision_created.v1` | workouts | validation/audit |
| `workouts.revision_approved.v1` | workouts | publish eligibility |
| `workouts.scheduled.v1` | workouts | notifications/calendar |
| `garmin.sync_requested.v1` | garmin | worker |
| `garmin.activity_discovered.v1` | garmin | fetch/normalize |
| `activities.file_stored.v1` | activities | normalize |
| `activities.normalized.v1` | activities | analyze/match |
| `analytics.activity_analyzed.v1` | analytics | metrics/progress |
| `feedback.session_recorded.v1` | activities | planning/readiness |
| `actions.proposal_ready.v1` | actions | notifications/audit |
| `actions.proposal_approved.v1` | actions | execution eligibility |
| `actions.execution_requested.v1` | actions | worker |
| `garmin.workout_published.v1` | garmin | binding/calendar |
| `planning.week_proposed.v1` | planning | PWA/plugin |
| `operations.job_failed.v1` | operations | alert/audit |

Eventos são fatos no passado, imutáveis, versionados e sem segredos.
