# Garmin pool-swim data semantics

This document records what the Swim Coach knows about Garmin pool-swim fields.
It deliberately distinguishes a field/unit defined by an upstream profile from an
interpretation inferred from observed data. A field name alone is not evidence of its
calculation basis.

## Evidence and status

- **DOCUMENTED**: the pinned upstream library or official FIT profile defines the field,
  scale, or unit.
- **INFERRED**: the interpretation is supported by source inspection and/or numeric
  relationships in a sanitized activity, but the upstream endpoint does not publish a
  contract for it.
- Raw Garmin values are preserved before normalization. A normalized value derived from an
  inferred unit remains `INFERRED`; conversion does not promote it to documented fact.
- No authenticated Garmin API read or remote write was performed for this investigation. The
  athlete supplied the original Garmin Connect download as a private ZIP containing one intact
  FIT file. That private archive, its Garmin identifier, and personal timestamps are not
  versioned. A sanitized allowlisted projection of the decoded FIT messages is versioned for
  regression testing. Field presence and numeric relationships described below are therefore
  confirmed for this artifact; private Garmin algorithms and undocumented Connect endpoint
  semantics remain `INFERRED`.

## Sources and current pipeline

The repository pins these two separate integrations:

1. `garminconnect[workout]==0.3.10`, an unofficial Garmin Connect wrapper. Its
   `get_activities(start, limit)` method reads
   `/activitylist-service/activities/search/activities`; its
   `download_activity(..., ORIGINAL)` method reads
   `/download-service/files/activity/{activity_id}`. The wrapper passes activity-list JSON
   through without applying a pool-length schema.
2. `garmin-fit-sdk==21.208.0`, Garmin's official decoder and FIT profile. The decoder applies
   FIT scale/offset to ordinary typed fields before returning message dictionaries. The
   polymorphic `workout_step.duration_value` remains an encoded integer in the observed SDK
   output, so its documented subfield scale must be selected from `duration_type` by the
   workout adapter.

The read pipeline is:

```text
Garmin Connect activity-list JSON
  -> GarminConnectProvider / GarminActivitySummaryDTO
  -> allowlisted raw summary + summary Activity
  -> immutable ORIGINAL download (ZIP or FIT)
  -> Garmin FIT SDK decoded messages
  -> normalized activity/laps/intervals/lengths
  -> derived analysis
  -> application services
  -> REST/MCP presentation
```

The activity-list JSON and decoded FIT messages are different sources. A conversion needed
for the JSON summary must not be applied again to a value already scaled by the FIT SDK.

## Garmin Connect activity-list fields

The endpoint is unofficial and publishes no versioned field schema. Consequently all units
and calculation bases in this table are currently **INFERRED**, even when the relationship is
strong.

| Raw field | Adapter field | Current interpretation | Evidence and handling |
|---|---|---|---|
| `activityId` | `external_id` | Provider identifier | Preserved as a string; never used as an internal primary key. |
| `activityType.typeKey` | `subtype` | Activity subtype | Pool reads accept `lap_swimming` and `pool_swimming`. |
| `startTimeGMT` | `start_time_utc` | UTC instant | Parsed as GMT and normalized to an aware UTC datetime. The raw string is retained. |
| `startTimeLocal` | `start_time_local_wall` | Local wall-clock components | Parsed as a naive datetime. It does **not** prove an IANA timezone. The raw string is retained; an included numeric offset generates a warning instead of being treated as the athlete timezone. |
| — | `timezone` | IANA timezone unavailable | The provider returns `None`. The application layer must apply the athlete profile timezone and derive a zoned local instant from `start_time_utc`. |
| `distance` | `distance_m` | Metres | `860` agrees with 43 active lengths in a 20 m pool. |
| `elapsedDuration` | `elapsed_seconds` | Elapsed duration in seconds | The incident value is `2089.629`. When absent, legacy fallback to `duration` is explicit and warned. |
| `duration` | `timer_seconds` | Timer duration in seconds | The incident value `2075.559` equals the sum of all detailed interval durations. This is strong but still endpoint-specific evidence. |
| `movingDuration` | `moving_seconds` | Garmin-reported summary moving duration in seconds | The Connect incident observation was `1699.541`. It is retained in the private raw summary and its provenance for debugging/reprocessing. The downloaded FIT does **not** contain `session.total_moving_time`; its active-length timer sum happens to equal `1699.541`. This relationship does not prove that Connect `movingDuration` and FIT active-length time have identical semantics. If the summary field is missing, the adapter returns `None`; it never copies timer duration. After FIT promotion this summary value is not published as canonical FIT moving time. |
| `poolLength` | `pool_length_m` | Hundredths of a metre -> metres | The incident raw value `2000` normalizes via `2000 / 100 = 20`; `43 * 20 = 860`. The conversion is source-specific and tagged `INFERRED`. |
| `numberOfActiveLengths` | `length_count` | Count of active lengths | `43 * 20 m = 860 m` in the incident. It is used as corroborating evidence, not to rewrite distance. |
| `averagePace` | legacy `avg_pace_seconds_per_100m` | Garmin-reported average pace; basis unconfirmed | Preserved with provenance. Do not assume it equals timer/distance or moving/distance, and do not silently replace it with either derived pace. |
| `averageSwimCadenceInStrokesPerMinute` | `avg_stroke_rate` | Garmin-reported stroke cadence | Unit is inferred from the Connect field name; calculation population is unconfirmed. |
| `avgStrokes` | `avg_strokes_per_length` | Garmin-reported average strokes | Calculation population and exclusions are unconfirmed. |
| `avgSwolf` | `avg_swolf` | Garmin-reported SWOLF | Calculation population is unconfirmed. It must be contextualized by pool length, stroke, and pace. |

### Summary adapter invariants and warnings

The adapter applies exactly one source-specific conversion:

```text
normalized pool length in metres = activity-list poolLength / 100
```

It records the raw field, endpoint, units, transformation, status, and the independent
`active lengths * normalized pool length == distance` check in DTO provenance. It emits:

- `GARMIN_SUMMARY_POOL_LENGTH_UNIT_INFERRED` whenever that inferred conversion is used;
- `GARMIN_SUMMARY_POOL_LENGTH_DISTANCE_MISMATCH` when the corroborating relationship fails;
- `GARMIN_SUMMARY_POOL_LENGTH_FRACTIONAL_METRES_UNSUPPORTED` rather than rounding or
  truncating a value the current integer-metre domain cannot represent. This is fail-closed:
  the normalized pool length is returned as unavailable while the raw value, candidate
  fractional value, provenance and warning remain inspectable;
- `GARMIN_SUMMARY_MOVING_DURATION_MISSING` rather than treating timer duration as moving;
- explicit warnings for elapsed/timer fallback and an offset-bearing local wall time.

A mismatch is a data-quality signal, not permission to force the invariant. Garmin can
legitimately contain incomplete lengths, drill transitions, edited distance, or device errors.
Because the endpoint unit and calculation basis of `averagePace` remain unconfirmed, an
unprocessed v2 summary does not expose it under a seconds-per-100-metre field. The allowlisted
raw value remains private for investigation; v1 keeps its historical projection, and v2 only
publishes `pace_from_garmin_reported_speed_s_per_100m` after canonical FIT speed normalization.

### Migration of legacy summary rows

Migration `000012_activity_canonical_v2` repairs the timezone on `garmin-summary-v1` activity
rows from the owning athlete's configured IANA timezone; it does not preserve the former
hard-coded `UTC` assertion as local time. Pool-length conversion is intentionally narrower:
the migration divides the stored value by 100 and promotes a row to `garmin-summary-v2` only
when the value is positive and exactly divisible by 100, active-length count is present, and
`converted pool length * active lengths == stored distance`. Rows without that independent
corroboration remain v1 and are not promoted by the migration. They remain visible in v2
activity lists as degraded entries: unambiguous summary facts such as distance, elapsed and
timer remain available, while ambiguous canonical facts such as pool and moving are null and
data quality explains that FIT/canonical normalization is unavailable.

The migration deliberately leaves the physical parser-v1
`moving_seconds = timer_seconds` value byte-for-byte intact so a legacy-only database can be
downgraded. Canonical v2 views recognize the v1 parser marker: the activity remains listed,
but `durations.moving_s` is null instead of publishing that ambiguous alias. Local FIT
reprocessing creates a separate v2 normalization with provenance and warnings. Because a
populated v2 normalization cannot be represented by the v1 schema without
losing nullable clocks, classifications and provenance, downgrade is blocked before schema
mutation when any canonical-v2 normalization (or nullable legacy moving fact) exists.

## Official FIT fields after SDK decoding

The profile in `garmin_fit_sdk/profile.py` is generated from FIT Profile 21.208.0. Its field
names, scales, units, and enums below are **DOCUMENTED**. Statements about a device's
internal detection algorithm remain **INFERRED**.

| FIT message/field | SDK value | Status | Swim Coach meaning |
|---|---|---|---|
| `session.total_elapsed_time` | seconds; FIT scale 1000 already applied | DOCUMENTED field/unit | The supplied FIT contains `2089.629`. Preserve as the elapsed clock independently of timer time. |
| `session.total_timer_time` | seconds; scale 1000 | DOCUMENTED field/unit | The supplied FIT contains `2075.559`. It equals the sum of all 61 decoded length timer durations and the sum of all lap timer durations. |
| `session.total_moving_time` | seconds; scale 1000 | DOCUMENTED field/unit | Garmin-reported moving clock when emitted. This field is **absent** from the supplied FIT, so canonical FIT moving time is null; `1699.541` must not be inserted here from active lengths. |
| `session.total_distance` | metres; scale 100 | DOCUMENTED field/unit | The supplied FIT contains `860`. Garmin session distance is canonical when present, including explicit zero. Preserve the active-length reconstruction as corroborating provenance and warn when they differ; use the reconstruction only when this field is absent. |
| `session.pool_length` | metres; scale 100 | DOCUMENTED field/unit | The supplied FIT contains SDK-scaled `20`. **Do not divide by 100 again.** |
| `session.pool_length_unit` | FIT enum | DOCUMENTED | The supplied FIT contains `metric`; retain the pool configuration unit for quality checks. |
| `session.num_active_lengths` | lengths | DOCUMENTED | The supplied FIT contains `43`, equal to the 43 decoded `ACTIVE` length messages. |
| `session.workout_rpe` | unsigned integer encoding Borg CR10 multiplied by 10 | DOCUMENTED field/encoding | The supplied FIT SDK output is `30`, normalized to canonical Borg CR10 `3.0` by `value / 10`. Accept the documented `0..100` encoded range as `0.0..10.0`; do not confuse it with workout-step intensity. The profile's ordinary numeric `scale` remains 1; the ×10 convention is part of the field definition. |
| `session.workout_feel` | unsigned integer; no scale | DOCUMENTED field/scale | The supplied FIT contains `75`, preserved as canonical `feeling_score=75` on a `0..100` scale. Feeling is not a technique score. |
| `session.avg_speed` | metres/second; scale 1000 | DOCUMENTED field/unit | Garmin-reported speed. Its calculation population is not specified by the field definition, so preserve it before deriving pace. |
| `session.enhanced_avg_speed` | metres/second; scale 1000 | DOCUMENTED field/unit | The supplied FIT contains `0.506`. It derives to `197.628 s/100 m`; what Garmin includes in this speed remains INFERRED. |
| `lap.total_elapsed_time` | seconds; scale 1000 | DOCUMENTED field/unit | Lap elapsed clock. |
| `lap.total_timer_time` | seconds; scale 1000 | DOCUMENTED field/unit | Lap timer clock; not automatically swimming time. |
| `lap.total_moving_time` | seconds; scale 1000 | DOCUMENTED field/unit | Garmin-reported lap moving clock when present. |
| `lap.total_distance` | metres; scale 100 | DOCUMENTED field/unit | A zero-distance temporal lap with decoded idle-length evidence can normalize as rest; without source evidence it remains unknown. Planned-workout context may reinterpret that unknown only in analysis, not rewrite the normalized Garmin fact. |
| `lap.swim_stroke` | FIT enum | DOCUMENTED | Detected stroke at lap level; keep separate from planned stroke. |
| `lap.total_strokes` | strokes (swimming sub-field) | DOCUMENTED field/unit | Garmin stroke count for the lap when emitted. |
| `lap.avg_cadence` | rpm | DOCUMENTED field/unit, INFERRED interpretation | The profile calls this generic cadence, not swimming strokes/minute. Mapping it to canonical stroke rate remains explicitly inferred. |
| `lap.enhanced_avg_speed` | metres/second; scale 1000 | DOCUMENTED field/unit | Preserved as the Garmin speed fact. In the first 80 m lap it is `0.592`, deriving to `168.919 s/100 m`; its private calculation basis remains INFERRED. |
| `length.length_type` | FIT `active`/`idle` enum | DOCUMENTED | Active and idle lengths must both be retained. Idle is not a zero-distance work repetition. |
| `length.total_elapsed_time` | seconds; scale 1000 | DOCUMENTED field/unit | Length elapsed duration. |
| `length.total_timer_time` | seconds; scale 1000 | DOCUMENTED field/unit | Length timer duration. |
| `length.total_strokes` | strokes | DOCUMENTED field/unit | Stroke count for that length when emitted. |
| `length.avg_speed` | metres/second; scale 1000 | DOCUMENTED field/unit | Garmin-reported length speed. |
| `length.swim_stroke` | FIT enum | DOCUMENTED | Detected length stroke. |
| `length.avg_swimming_cadence` | strokes/minute | DOCUMENTED field/unit | Length cadence. |
| `workout_step.message_index` | zero-based step index | DOCUMENTED | Stable reference used by repeat messages; it is not a display order inferred from names. |
| `workout_step.duration_type` | FIT enum | DOCUMENTED | Selects the applicable `duration_value` subfield, including `distance`, `time`, and `repeat_until_steps_cmplt`. |
| `workout_step.duration_value` for `distance` | hundredths of a metre | DOCUMENTED field/unit | The supplied FIT raw values `16000`, `4000`, and `8000` normalize exactly once to 160 m, 40 m, and 80 m. |
| `workout_step.duration_value` for `time` | milliseconds | DOCUMENTED field/unit | The supplied FIT raw values `20000` and `25000` normalize exactly once to 20 s and 25 s. |
| `workout_step.duration_value` for `repeat_until_steps_cmplt` | first repeated message index | DOCUMENTED subfield meaning | Values `1`, `6`, and `9` point to the first step in each repeated span; they are not durations and receive no unit conversion. |
| `workout_step.target_value` for `repeat_until_steps_cmplt` | repetition count | DOCUMENTED subfield meaning | Values `2`, `4`, and `4` expand the referenced spans while preserving set and repetition identity. |
| `workout_step.intensity` | FIT enum | DOCUMENTED | Preserves `warmup`, `active`, `rest`, and `cooldown` intent independently from detected activity stroke. |

The standard length definition in the pinned FIT profile contains neither
`total_moving_time` nor `avg_swolf`. If a decoder/device extension emits either name it is
preserved as a Garmin value, but its interpretation is explicitly `INFERRED`. Otherwise length
moving time stays nullable, and SWOLF may be a Garmin Connect aggregate or a derived value. A
derived length SWOLF must document the duration basis and stroke-count convention.

The standard session/lap definitions also contain no `avg_swolf`. A decoded field with that
name is retained without claiming standard FIT semantics. Parser `2.1.0` records
`pool_length_unit`, compares `session.num_active_lengths` with decoded active lengths, and
keeps both the Garmin-reported and decoded counts in provenance. It also normalizes the
documented session evaluation fields without consulting or assigning semantics to similarly
named Garmin Connect summary fields.

### Confirmed structure of the supplied FIT

The private FIT decodes successfully and contains 61 length messages: 43 `ACTIVE` and 18
`IDLE`. The enums, timer fields, distance, pool length and units are documented FIT facts.
Their sums are deterministic derived facts:

```text
43 ACTIVE length timer durations = 1699.541 s  -> canonical swim_duration_s
18 IDLE length timer durations   =  376.018 s  -> canonical explicit rest_duration_s
all 61 length timer durations    = 2075.559 s  -> session.total_timer_time
```

Several temporal laps in this FIT report `num_lengths=0` while the range from their
`first_length_index` to the following lap boundary contains exactly one `IDLE` length. Since
parser `2.0.4`, that length is owned through the narrow, visible
`LAP_IDLE_LENGTH_OWNERSHIP_INFERRED` rule. It does not widen positive counts or absorb
`ACTIVE`/`UNKNOWN` gaps: those produce `LAP_LENGTH_INDEX_COUNT_MISMATCH`, remain unassigned,
and lower data quality. A lap whose owned active-length distance disagrees with
`lap.total_distance` receives `LAP_ACTIVE_LENGTH_DISTANCE_MISMATCH` rather than a silent
correction.

The FIT session does not carry `total_moving_time`. Consequently `1699.541 s` is a
`DERIVED` active-length swim duration in the FIT-normalized model, not a documented Garmin
moving-duration fact. Its equality with the Connect summary observation is useful
corroboration, but claiming the same internal Garmin algorithm would remain `INFERRED`.
After this FIT normalization is promoted, canonical/public `durations.moving_s` is therefore
null. The distinct Connect `movingDuration=1699.541` observation remains preserved in the
private raw summary and provenance; it is neither discarded from raw storage nor substituted
for the absent FIT moving field.

The same supplied FIT confirms the post-session athlete evaluation independently from its
swim clocks and metrics:

```text
session.workout_rpe  = 30 -> 30 / 10 = Borg CR10 3.0
session.workout_feel = 75 -> feeling score 75/100
```

Both values retain `GARMIN` provenance, their FIT raw field and the documented transformation.
Manual values are separate field-level overrides; an override never rewrites the immutable FIT
fact. No claim is made about Garmin Connect activity-list fields because this evidence comes
from the decoded FIT session message.

The lap/length assignment supplies a second exact decomposition:

```text
positive-distance lap timer total = 1807.915 s
  ACTIVE length timer total        = 1699.541 s
  IDLE within positive laps        =  108.374 s
zero-distance lap timer total      =  267.644 s
timer total                        = 2075.559 s
elapsed - timer                    =   14.070 s
```

This confirms that positive lap distance does not imply uninterrupted swimming: `108.374 s`
of FIT-classified idle time occurs inside positive-distance laps. Conversely, the
zero-distance lap total is backed by decoded idle lengths, so these laps can normalize as
`REST` rather than relying on planned-workout inference.

The first 80 m lap demonstrates why Garmin speed and timer pace are separate facts:

```text
lap timer duration                    158.171 s -> 197.714 s/100 m
ACTIVE length timer duration          135.171 s -> 168.964 s/100 m
lap enhanced_avg_speed                  0.592 m/s -> 168.919 s/100 m
```

The close agreement between enhanced-speed pace and active-length swim pace, and their large
difference from timer pace, is confirmed numeric evidence for this lap. Inferring that Garmin
always calculates enhanced speed from active-length time would go beyond the public FIT field
definition, so that algorithmic interpretation remains `INFERRED`.

### Confirmed planned workout in the supplied FIT

The FIT also contains 13 `workout_step` messages. They confirm the planned structure without
requiring a workout title, step name, description, Garmin identifier, or timestamp:

```text
message 0:       160 m WARMUP
messages 1..4:  (40 m ACTIVE + 20 s REST + 40 m ACTIVE + 20 s REST) x 2
messages 6..7:  (80 m ACTIVE + 25 s REST) x 4
messages 9..10: (40 m ACTIVE + 20 s REST) x 4
message 12:       80 m COOLDOWN
```

Repeat messages 5, 8, and 11 use `duration_type=repeat_until_steps_cmplt`.
Their `duration_value` values (`1`, `6`, `9`) reference the first repeated message index, and
their `target_value` values (`2`, `4`, `4`) provide the repetition count. Expanding those
references yields `880 m` planned distance and `260 s` prescribed rest. Against the FIT
session distance of `860 m`, planned-versus-actual is therefore confirmed as:

```text
planned distance = 880 m
actual distance  = 860 m
difference       = -20 m
```

The FIT workout fields confirm structure, distance, duration, repeat identity and intensity.
They do not make private workout or step names necessary for normalization, and those names
are excluded from the sanitized projection.

## Analysis interpretation boundaries

- Equivalent-set analysis groups contiguous repetitions with the same distance, detected
  stroke, planned role, planned intensity and target pace range. Each set selects and exposes
  the one pace basis with greatest repetition coverage; moving, active-length swim and timer
  break ties in that order. Pace bases are never mixed within a set, and missing repetitions
  remain visible through `missing_pace_indices` with downgraded confidence.
- Cross-set speed/endurance profiles select a single basis by the greatest non-null coverage
  across eligible freestyle `WORK` intervals; moving wins ties. The response discloses
  `profile_pace_basis` and flags unavailable or non-moving series.
- Robust outlier detection only emits statistical inspection flags inside equivalent runs.
  Those flags do not automatically exclude an interval. Set and profile exclusion requires an
  explicit `is_outlier`/`outlier` marker or the additive persisted quality warning
  `EXCLUDE_FROM_FITNESS` already present on the normalized interval.
- Goal-readiness evidence considers continuous freestyle blocks reconstructed from active FIT
  lengths as well as comparable intervals. Length-based evidence carries basis `swim_length`.
  Efforts below `min(400 m, goal distance)` remain short-distance evidence and cannot establish
  goal-specific confidence; low-quality evidence never produces `ACHIEVED`.
- The `technique` profile member is contextual efficiency evidence, not a score. It preserves
  stroke/SWOLF alongside swim pace and quality, and does not infer that lower SWOLF alone means
  better technique.
- Stroke/SWOLF aggregates use active lengths grouped by pool length, stroke, length distance,
  planned role and 15 s/100 m swim-pace band.
- Historical comparisons require the same pool length, repetition distance/count, detected
  stroke, planned role, planned intensity, target pace range, planned rest and explicit pace
  basis in at least two distinct sessions.
  They compare pace, CV, fade, actual rest, RPE and only unambiguously matched swim-pace-band
  stroke/SWOLF evidence; session-wide averages are not used as a substitute.
- Automatic planned-workout matching compares its rest-inclusive estimated total duration to
  canonical timer duration and records `duration_basis="timer_duration_s"`.
- Session evaluation resolves each field independently: manual override first, then Garmin FIT,
  then unavailable. sRPE uses the effective RPE and canonical timer duration, records both the
  duration basis and RPE source, and treats Garmin feeling as a separate contextual signal.
  Weekly planning applies a separate Swim Coach ruleset choice: an effective feeling score at
  or below `25/100` from the seven days before the planned week adds a conservative recovery
  signal. This threshold and lookback are product policy, not Garmin/FIT semantics or a clinical
  interpretation; older low-feeling observations do not repeatedly force recovery weeks.
- When ordered alignment matches a planned `REST` to a normalized `UNKNOWN` interval with zero
  distance, the analysis overlay may contextualize its timer duration as rest and emits
  `REST_CLASSIFIED_FROM_PLANNED_WORKOUT`. The stored normalized interval remains `UNKNOWN`.
- A planned pace range is interpreted against the explicitly disclosed swim-pace basis. It
  produces a planned duration range for the planned distance, never an exact duration from the
  range midpoint. If swim duration/pace is unavailable, compliance remains unknown rather than
  falling back to a different basis.
- Equivalent sets containing `UNKNOWN` interval types cannot receive `HIGH` confidence and do
  not publish fade. Goal-readiness confidence is capped by canonical normalization quality.
- Analysis cache version `swim-analysis:2.1.0` records these semantic boundaries.
- Stationary time known only at interval level is not assigned to an arbitrary length. If it
  cannot be reconciled with length-level stationary facts, every affected length becomes a
  conservative continuity boundary and the analysis emits
  `INTERVAL_STATIONARY_LOCATION_UNKNOWN`.
- An unplanned rest of at least 60 seconds separates adjacent inferred sets when no planned set
  identity exists; the boundary is disclosed as inferred and is not attributed to either set.

## Incident evidence and root causes

Sanitized incident facts:

```text
distance                      860 m
activity-list poolLength      2000
active lengths                43
Connect movingDuration observation     1699.541 s
FIT session.total_moving_time          absent
FIT session.total_timer_time           2075.559 s
FIT session.total_elapsed_time         2089.629 s
FIT ACTIVE length timer sum            1699.541 s
FIT IDLE length timer sum               376.018 s
FIT positive-distance lap timer sum    1807.915 s
FIT zero-distance lap timer sum         267.644 s
```

Relationships:

```text
2000 / 100 = 20 m
43 * 20 = 860 m
1807.915 + 267.644 = 2075.559 s
1699.541 + 376.018 = 2075.559 s
2075.559 / 860 * 100 = 241.344 s/100 m
1699.541 / 860 * 100 = 197.621 s/100 m
```

The pre-v2 implementation had these independent root causes:

1. The summary adapter copied `poolLength=2000` directly into a metre field. The FIT parser,
   however, received `session.pool_length` already scaled to `20` by the official SDK. This
   created two pool lengths for one activity.
2. The FIT normalizer assigned `moving_seconds = timer_seconds`, ignoring the documented
   nullable `session.total_moving_time` field. The real FIT confirms that this field is absent,
   so detail should expose moving as unavailable and separately derive `swim_duration_s` from
   active lengths. The Connect summary observation and detail previously exposed different
   meanings under the same name.
3. The FIT normalizer built every lap as `work`; a temporal zero-distance lap consequently
   lost its explicit-rest/unknown-transition meaning.
4. Interval pace was derived from lap timer time and exposed as a generic average pace. The
   Garmin-reported speed and its derived pace were not preserved separately, so divergent clocks became
   indistinguishable.
5. The summary adapter discarded `startTimeLocal` and asserted `timezone="UTC"`. UTC was
   valid for the instant but false as the athlete's local timezone.

The decoded FIT confirms `108.374 s` of idle lengths inside positive-distance laps,
`267.644 s` of idle-backed zero-distance laps, and `14.070 s` outside the timer. Thus all
`376.018 s` of decoded idle length time is explicit Garmin/FIT rest evidence in the canonical
model. The embedded workout prescribes `260 s` of `REST`; the remaining `116.018 s` is real
idle time beyond that planned total. Whether Garmin's private movement algorithm uses the
same boundaries remains inferred because `session.total_moving_time` is absent.

## Integration contract

- `GarminActivitySummaryDTO.timezone` is nullable. `None` means the provider did not supply an
  IANA timezone; it does not mean UTC.
- `start_time_utc` is the canonical instant from `startTimeGMT`.
- `start_time_local_wall` preserves Garmin's displayed local clock without attaching an
  invented zone.
- Summary DTO `moving_seconds` is nullable and only contains Connect `movingDuration`; it
  never falls back to `timer_seconds`. This source fact is persisted in the private raw
  summary/provenance. Once a FIT normalization is promoted, public canonical
  `durations.moving_s` comes only from FIT `session.total_moving_time`; absence in this FIT
  produces null rather than falling back to the summary observation.
- `pool_length_m` contains the activity-list-specific normalized value. The unchanged
  `poolLength` remains in `raw_safe`.
- `provenance` and `warnings` travel with the DTO so the application layer can persist them
  into v2 normalization/data-quality records. They are diagnostic metadata and do not expose
  the raw payload publicly.
- REST v2 exposes activity reads plus versioned aliases for process, feedback and manual-match
  mutations. These reuse the existing authentication, CSRF and applicable idempotency
  semantics; none exposes the raw summary or FIT payload.
- REST/MCP v2 exposes `session_evaluation.garmin`, `manual_override`, `effective` and field-level
  provenance. Saving technique, pain or notes may omit manual RPE when a canonical Garmin RPE
  exists; only an explicitly supplied manual value becomes an override. REST v2 feedback is a
  full replacement, so omission clears a prior field override and an empty replacement deletes
  an existing all-manual record. V1 keeps its required integer RPE projection for compatibility.

The application service must use the athlete's configured IANA timezone (for the incident,
`America/Sao_Paulo`) to derive a zoned local timestamp from `start_time_utc`, then compare its
wall clock with `start_time_local_wall` and warn on disagreement.
