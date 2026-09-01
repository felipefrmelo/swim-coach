# Canonical pool-activity model v2

This document defines the domain boundary introduced by parser/analysis v2. Source-specific
facts are normalized once; presentation code is not allowed to reinterpret Garmin fields.
Field-level upstream evidence is recorded in
[`garmin-swim-data-semantics.md`](garmin-swim-data-semantics.md).

## Pipeline and clocks

```text
allowlisted Garmin summary + immutable local FIT
  -> source-specific adapters
  -> canonical activity / lap / interval / length facts
  -> planned-step alignment
  -> contextual analysis
  -> REST/MCP v2 views
```

All distances are integer metres, durations are decimal seconds, and paces are decimal
seconds per 100 m. The current integer-metre domain cannot represent a pool length that
normalizes to fractional metres. Source adapters fail closed in that case: pool length is
left unavailable and a quality warning is retained rather than rounding or truncating it.

| Canonical concept | Definition |
|---|---|
| `elapsed_duration_s` | FIT `total_elapsed_time`; wall-clock extent represented by the FIT aggregate. |
| `timer_duration_s` | FIT `total_timer_time`; time for which the activity timer was active. |
| `moving_duration_s` | In a promoted FIT normalization, Garmin FIT `session.total_moving_time` only; nullable and never copied from timer or Connect summary. Connect `movingDuration` remains a separate private raw-summary fact with provenance. Garmin's detection algorithm is not inferred from the name. |
| `swim_duration_s` | Sum of canonical active-length timer durations. It is derived and intentionally distinct from Garmin moving time. |
| `rest_duration_s` | Time explicitly represented by an idle length or a zero-distance rest interval. Unknown stationary time is not silently called rest. |
| `stationary_duration_s` | Derived `timer - moving - explicit rest` when all three inputs exist and are consistent. |
| outside-timer time | `elapsed - timer`; exposed through the two facts rather than relabelled. |

The activity, lap, interval and length models preserve each applicable clock separately.
Invariant violations such as `moving > timer` or `timer > elapsed` create data-quality
warnings; they do not reject an otherwise inspectable Garmin artifact.
Missing moving time, inferred pool length, synthesized laps or missing lengths cap canonical
quality at `PARTIAL`; contradictory duration/distance invariants cap it at `POOR` while the
raw facts remain available for inspection and reprocessing.

## Pace facts

- `garmin_reported_speed_m_per_s`: the original SDK-scaled Garmin speed fact, tagged
  `GARMIN` and persisted without relabelling it as pace. Provenance records its FIT
  field/unit semantics as `documented` but its Garmin calculation population as
  `inferred`;
- `pace_from_garmin_reported_speed_s_per_100m`: derived only from that speed fact
  (`100 / garmin_reported_speed_m_per_s`) and tagged `DERIVED`; its provenance carries
  the inferred calculation basis of the input speed;
- `moving_pace_s_per_100m`: `moving_duration_s / distance_m * 100`;
- `swim_pace_s_per_100m`: `swim_duration_s / distance_m * 100`;
- `timer_pace_s_per_100m`: `timer_duration_s / distance_m * 100`;
- `session_pace_s_per_100m`: `elapsed_duration_s / distance_m * 100`.

No individual pace silently falls back to another basis. Equivalent-set analysis selects one
basis independently for each contiguous distance/stroke/role/intensity/target-equivalent set.
With `pace_basis="best_available"`, it selects the basis with the greatest repetition
coverage; moving, active-length swim and timer are used in that order only to break a coverage
tie. It never mixes bases inside the same set. Missing repetitions are published as
`missing_pace_indices`, lower the confidence and produce a basis-specific quality reason.
Every serialized set carries its selected `pace_basis`, the analysis carries
`set_pace_basis="per_set_explicit"`, and a stable reason is emitted for each non-moving set
basis.

The cross-set speed/endurance profile needs one common basis. It counts non-null moving,
swim and timer paces across the eligible freestyle `WORK` candidates, chooses the basis with
the greatest coverage, and gives moving pace precedence on ties. The choice is exposed as
`profile_pace_basis`; a missing series or selection of a non-moving basis produces an explicit
quality reason.

The v1 `average_pace_seconds_per_100m` analysis alias remains frozen to its historic timer
basis during transition. V2 clients must use the explicit `paces` object.
The v2 `speeds.garmin_reported_m_per_s` fact exposes the preserved Garmin value next to
the derived pace; a missing source speed remains `null` and is never reconstructed from one of
the internal pace bases.

## Interval, workout and stroke concepts

Provider-neutral interval type and workout intent are separate dimensions:

- interval type: `SWIM`, `REST`, `DRILL`, `UNKNOWN` (`work` is accepted only when reading
  v1 normalizations);
- planned role: `WARMUP`, `WORK`, `RECOVERY`, `REST`, `COOLDOWN`, `DRILL`, `OTHER`;
- detected stroke and planned stroke remain distinct.

FIT lengths retain `ACTIVE`, `IDLE` and `UNKNOWN`. An active length has pool distance; an
idle length has zero distance. A timed zero-distance lap is normalized as `REST` only when
decoded FIT length evidence supports it. Without that source evidence it remains `UNKNOWN`
and carries `ZERO_DISTANCE_INTERVAL_WITHOUT_REST_EVIDENCE`.

Lap ownership normally follows `first_length_index + num_lengths`. The only widening rule is
an explicitly warned Garmin pattern where `num_lengths=0` and every message before the next
lap boundary is `IDLE`. Other count/boundary gaps remain unassigned and generate quality
warnings; unknown future `length_type` enums keep Garmin raw-field provenance but are mapped to
canonical `UNKNOWN` with inferred interpretation.

Ordered step alignment may match such an `UNKNOWN`, zero-distance interval to a planned
`REST`. In that case only the analysis overlay contextualizes it as rest, records
`interval_type_source="planned_workout"`, uses its timer duration as rest when no explicit
rest duration exists, and emits `REST_CLASSIFIED_FROM_PLANNED_WORKOUT`. The immutable
normalized interval and its persisted Garmin-derived classification are not rewritten.

Repeat expansion preserves set and repetition identity. Ordered planned-versus-actual
alignment scores type, distance/duration and stroke, then persists per-step differences,
confidence and unmatched steps in the versioned analysis record. Actual step pace is also
reported with its selected basis. Automatic workout matching compares the planned estimated
total duration with canonical `timer_duration_s`, because the planned estimate includes
explicit rests; the match score records `duration_basis="timer_duration_s"`.

For FIT-embedded workouts, `workout_step.duration_value` is decoded according to its
`duration_type`: distance uses hundredths of a metre, time uses milliseconds, and
`repeat_until_steps_cmplt` uses the value as the first repeated message index rather than a
duration. Its `target_value` is the repetition count. This source identity is retained during
expansion; presentation code must not flatten the steps and then guess set boundaries.

## Contextual analysis

Analysis v2 includes:

- pace aggregates by planned role and explicit pace basis;
- freestyle work limited to positive-distance intervals explicitly classified as `SWIM` with
  freestyle `WORK` context, excluding `UNKNOWN`, rest, drill and cooldown roles;
- equivalent-set mean, best, worst, amplitude, population CV, linear trend, negative split,
  fade between halves and actual/planned rest on the set's disclosed pace basis. Planned target
  compliance has its own disclosed `swim` basis and remains unknown when swim pace is missing;
- robust statistical outlier checks only inside contiguous distance/stroke/role-equivalent
  runs. These checks produce inspection flags only; they are not copied into the source
  intervals and do not automatically remove a repetition from set or profile metrics.
  Exclusion requires an explicit quality marker already present on the input record
  (`is_outlier`/`outlier`, or persisted warning `EXCLUDE_FROM_FITNESS`), and the excluded
  interval indices remain visible in set output;
- continuous swims and exact 100/200/400/800 m freestyle windows from active lengths. Idle
  lengths, explicit rests and any positive canonical length stationary duration form hard
  boundaries; a length containing stationary time is isolated because the pause position inside
  it is unknown. If interval stationary time cannot be reconciled to individual lengths, all
  lengths in that interval are conservatively isolated and
  `INTERVAL_STATIONARY_LOCATION_UNKNOWN` is emitted;
- longest observed continuous distance under the goal pace, with no short-block
  extrapolation;
- speed, short-endurance and aerobic-endurance profiles on the selected profile basis;
- goal readiness using eligible interval evidence and continuous freestyle blocks reconstructed
  from active lengths. Evidence shorter than `min(400 m, goal distance)` remains useful for the
  speed/short-endurance dimensions but cannot raise goal-specific confidence. When length
  continuity supplies the evidence, its pace basis is disclosed as `swim_length`; readiness
  remains indeterminate until the goal distance itself is observed in an eligible interval or
  continuous length block. A selected low-quality sample can never produce `ACHIEVED`;
- `technique` represented as contextual efficiency evidence, not a technique score. It
  reports comparable active known-stroke lengths, their swim-pace context and evidence
  quality, without interpreting lower SWOLF as intrinsically better or calculating a goal
  pace gap;
- stroke count and SWOLF grouped for active lengths by pool length, stroke, length distance,
  planned role and a 15 s/100 m swim-pace band. Comparisons are valid only within the same
  context;
- historical trends only for equivalent-set signatures containing pool length, repetition
  distance/count, detected stroke, planned role, intensity, target pace range, selected pace
  basis and planned rest. The
  trend compares pace, CV, fade, actual rest, contextual stroke/SWOLF when an unambiguous
  swim-pace band exists, and session RPE. Two different pace bases or two different roles
  never share a trend, and at least two distinct sessions are required;
- data-quality level `HIGH`, `MEDIUM` or `LOW` with stable reason codes;
- dimension-level quality and reasons for continuity, distance bands, speed/endurance,
  technique, goal readiness, adherence, equivalent sets and contextual stroke/SWOLF groups;
- sRPE as `timer_duration_s / 60 * RPE`, with `duration_basis=timer_duration_s`.

For actual intervals without planned set identity, an unplanned rest of at least 60 seconds is
an inferred set boundary and emits `UNPLANNED_LONG_REST_SET_BOUNDARY_INFERRED`; the boundary
itself is not counted as the rest belonging to either adjacent set.

CSS is never estimated from ordinary activity data. A future CSS feature requires an
identified protocol such as a structured 400 m + 200 m test.

## Storage and provenance

Migration `000012_activity_canonical_v2` is additive for normalized activity, lap,
interval and length facts. Legacy columns remain readable. A normalization is immutable and
identified by FIT checksum plus parser version; promotion of a fully saved normalization is
atomic and reprocessing is idempotent.

Parser `2.1.0` treats a present `session.total_distance` as the canonical Garmin fact and
never overwrites it with `active lengths * pool length`. That reconstruction is retained as
corroborating provenance and raises a data-quality warning on disagreement; it becomes the
canonical distance only when the Garmin session field is absent. The same provenance records
the standard `session.pool_length_unit`, Garmin `session.num_active_lengths`, decoded active
length count, and persisted active-length count.

For legacy `garmin-summary-v1` activity rows, the migration replaces the hard-coded timezone
with the owning athlete's configured IANA timezone. It remaps `pool_length_m / 100` and
promotes the row to `garmin-summary-v2` only when the stored value is positive, exactly
divisible by 100, active-length count is present, and the converted pool length times that
count exactly corroborates stored distance. Uncorroborated rows remain v1 rather than being
promoted, but remain visible in v2 activity lists as degraded entries. Their unambiguous
summary distance/elapsed/timer facts remain available; ambiguous pool, moving and other
FIT-dependent canonical facts are null, with `LOW` data quality and reasons such as
`FIT_NORMALIZATION_UNAVAILABLE` or `LEGACY_NORMALIZATION_NOT_CANONICAL_V2`. Known parser-v1
timer aliases in `moving_seconds` remain physically intact for legacy-only downgrade, but
canonical v2 list views never publish those aliases as Garmin moving time. Local FIT
reprocessing writes a separate v2 normalization with the real nullable fact, provenance and
warnings.

The v1 schema cannot safely represent the populated v2 normalization. Migration downgrade is
therefore blocked before any destructive schema change whenever a canonical-v2 normalization
or nullable moving fact is persisted. An empty environment or one containing only intact
parser-v1 normalizations can still downgrade.

Each important canonical field can carry:

```json
{
  "source": "garmin | derived | planned_workout | inferred",
  "raw_field": "session.total_timer_time",
  "transformation": "...",
  "interpretation": "documented | inferred"
}
```

Raw provider summaries are allowlisted and persisted separately. This includes the Connect
`movingDuration` source observation and its provenance even when a promoted FIT normalization
has `moving_duration_s=null`. Original FIT files remain private immutable artifacts. Neither
raw summary nor FIT payload is returned by REST or MCP.

## Local-only operations

The following commands never contact Garmin:

```bash
uv run python backend/scripts/inspect_local_swim_fit.py --user-id UUID --activity-id UUID
uv run python backend/scripts/reprocess_local_swims.py --user-id UUID
```

Inspection prints the persisted summary and decoded FIT using separate explicit allowlists.
Provider identifiers, activity names and timestamps are omitted or redacted by default, and
unknown summary/FIT fields are denied. Unknown FIT
message types, future SDK fields, GPS, heart rate, profile/workout labels and nested values
are denied by default; absolute timestamps are redacted unless the local operator explicitly
passes `--include-timestamps`. The inspector still returns a sanitized persisted summary with
`fit_status="unavailable"` when no local FIT exists; `--require-fit` opts into a hard failure.
Reprocessing first reapplies the current summary adapter to the immutable local raw payload,
then reads only a checksum-verified local FIT when present, creates
parser v2 normalization/analysis idempotently and promotes it after persistence. Activities
without a local FIT are left unchanged and are listed as `skipped=FIT_FILE_UNAVAILABLE`.

## Public contracts

- REST/PWA activity reads use `/api/v2/activities` and typed response models.
- The v2 activity resource also exposes the existing authenticated mutation semantics at
  `POST /api/v2/activities/{activity_id}/process`,
  `PUT /api/v2/activities/{activity_id}/feedback`, and
  `PUT /api/v2/activities/{activity_id}/match`. Processing and feedback preserve their
  idempotency requirements; these are versioned aliases, not alternate domain interpretations.
- MCP v2 results use envelope `schema_version="2.0"`; its contract lives in
  `contracts/tool-result-envelope-v2.schema.json`.
- V2 exposes `started_at_utc`, `started_at_local`, `timezone`, explicit `durations`, preserved
  Garmin `speeds`, explicit derived `paces`, pool facts, provenance, data quality, sets and
  planned-versus-actual analysis. It also exposes `session_evaluation` with immutable Garmin
  FIT values, field-level manual overrides, effective values and provenance. Garmin
  `workout_rpe` is normalized from `0..100` to Borg CR10 `0.0..10.0`; `workout_feel` remains a
  separate `0..100` feeling score and is never treated as technique.
- V2 feedback may omit RPE when the activity already has an effective Garmin RPE. Sending an
  RPE or feeling score is an explicit field-level manual override; technique, pain and notes
  remain independent manual observations. PUT uses full-replacement semantics: omitting an
  existing RPE or feeling override clears that override, and an empty replacement removes the
  manual feedback row and returns `null`. An empty write with nothing to clear is rejected. V1
  retains its required integer RPE contract.
- Planning ruleset `1.1.0` carries effective RPE and feeling with their source. A feeling score
  at or below the Swim Coach threshold of `25/100` from the preceding seven days is a
  conservative recovery signal; that threshold is a versioned product rule, not a Garmin label
  or a clinical interpretation.
- After FIT promotion, v2 `durations.moving_s` is populated exclusively from FIT
  `session.total_moving_time`. It is null for this activity because that FIT field is absent;
  the private Connect raw-summary `movingDuration=1699.541` remains retained for debugging and
  reprocessing but is not republished as the FIT moving clock.
- V2 does not expose generic `started_local`, `moving_seconds`,
  `pace_seconds_per_100m` or a raw Garmin/FIT payload.
- The independent canonical workout contract remains `schema_version="1.0"`.

### MCP v1 transition

REST v1 remains mounted as a separate typed projection. With `mcp_v2_enabled=false`, the
legacy MCP catalogue uses dedicated v1 activity-list, activity-detail and goal-progress
projections and emits `schema_version="1.0"` for successes, validation/domain failures and
OAuth challenges. Its ambiguous pace/moving fields retain their historical meaning; they are
not populated from canonical v2 facts under a new interpretation. With the flag enabled, the
nine intent-level tools use the canonical v2 projections and envelope. Both JSON Schemas are
tested independently; the transition does not change the workout contract.

## Sanitized 860 m regression

The repository fixture is a sanitized allowlisted projection of the intact FIT supplied by
the athlete through a Garmin Connect ZIP download. The private ZIP, Garmin identifier, and
personal timestamps are not versioned. FIT message presence, SDK-scaled units and decoded enum
values are documented/confirmed source facts; derived sums carry `DERIVED` provenance.
Interpretations of Garmin's private algorithms and the undocumented Connect activity-list
schema remain `INFERRED`.

```text
Before (ambiguous): pool=2000 m, detail moving=2075.559 s,
                    average pace=241.344 s/100 m, rest=0

V2 canonical facts: pool=20 m metric, distance=860 m
                    lengths=61: 43 ACTIVE + 18 IDLE
                    moving=null (session.total_moving_time absent)
                    swim=1699.541 s, explicit FIT rest=376.018 s,
                    timer=2075.559 s, elapsed=2089.629 s,
                    swim pace=197.621, timer pace=241.344,
                    session pace=242.980 s/100 m
                    Garmin enhanced speed=0.506 m/s
                    pace from Garmin speed=197.628 s/100 m
                    planned=880 m, actual=860 m, difference=-20 m

Clock structure:    positive-distance laps=1807.915 s,
                    including 108.374 s of IDLE lengths
                    zero-distance laps=267.644 s, backed by IDLE lengths
                    elapsed outside timer=14.070 s

Embedded plan:      160 m WARMUP
                    (40 m + 20 s REST + 40 m + 20 s REST) x 2
                    (80 m + 25 s REST) x 4
                    (40 m + 20 s REST) x 4
                    80 m COOLDOWN
                    planned distance=880 m, prescribed REST=260 s
                    FIT idle beyond prescribed rest=116.018 s
```

The first 80 m lap has timer `158.171 s`, active-length swim time `135.171 s`, and Garmin
`enhanced_avg_speed=0.592 m/s`. These independently produce timer pace `197.714 s/100 m`,
swim pace `168.964 s/100 m`, and pace from Garmin speed `168.919 s/100 m`. Their divergence is
confirmed; the hypothesis that Garmin always bases enhanced speed on active-length time remains
`INFERRED` because the FIT profile documents the field and unit, not the device algorithm.

The sanitized projection preserves decoded idle lengths, Garmin speed, and 13 embedded
`workout_step` messages without inventing lap moving time: the source FIT contains no session
or lap `total_moving_time`. The `72.77 s` 20 m breaststroke detection is preserved, but the
embedded step metadata does not classify it as `DRILL`; any such label from the earlier
synthetic plan was inferred and must not be promoted to a Garmin fact. Fitness/outlier handling
must therefore use the confirmed step context and data quality instead of assuming a drill or
relabelling the length as a device error.
