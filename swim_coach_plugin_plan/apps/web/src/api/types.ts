export interface AuthConfig {
  oidc_enabled: boolean;
  dev_auth_enabled: boolean;
}

export interface Me {
  user: {
    id: string;
    email: string;
    display_name: string;
    locale: string;
    timezone: string;
    version: number;
  };
  profile: {
    experience_level: string;
    default_sessions_per_week: number;
    preferred_distance_unit: "m";
    default_pool_id: string | null;
    version: number;
  };
}

export interface Pool {
  id: string;
  name: string;
  length_m: number;
  is_default: boolean;
  location_label: string | null;
  active: boolean;
  version: number;
}

export interface AvailabilityRule {
  id: string;
  day_of_week: number;
  start_local_time: string;
  end_local_time: string;
  max_duration_minutes: number;
  pool_id: string | null;
  valid_from: string | null;
  valid_until: string | null;
  priority: number;
  version: number;
}

export interface Goal {
  id: string;
  title: string;
  status: "draft" | "active" | "completed" | "cancelled";
  priority: number;
  target_distance_m: number;
  target_duration_seconds: string;
  target_pace_seconds_per_100m: string;
  target_date: string | null;
  version: number;
}

export interface ProblemDetail {
  code: string;
  detail: string;
  correlation_id: string;
}

export interface GarminConnection {
  configured: boolean;
  status: "not_connected" | "disconnected" | "active" | "degraded" | "reauth_required" | "disabled";
  account_label_masked: string;
  provider_library_version: string | null;
  authenticated_at: string | null;
  last_success_at: string | null;
  last_error_code: string | null;
  connection_method: "server_bootstrap";
}

export interface GarminDevice {
  id: string;
  model: string;
  name: string;
  is_primary: boolean;
  last_seen_at: string | null;
}

export interface SwimActivity {
  id: string;
  name: string;
  subtype: string;
  start_time_utc: string;
  distance_m: number;
  elapsed_seconds: string;
  pool_length_m: number | null;
  length_count: number | null;
  avg_hr: number | null;
  avg_swolf: string | null;
}

export interface SwimActivityDetail {
  activity: SwimActivity;
  normalized: boolean;
  parser_version: string | null;
  profile_version: string | null;
  quality: "complete" | "partial" | "poor" | null;
  completeness: string | null;
  warnings: string[];
  intervals: Array<{
    index: number;
    interval_type: "work" | "rest";
    distance_m: number;
    duration_seconds: string;
    rest_seconds: string;
    pace_seconds_per_100m: string | null;
    stroke_type: string | null;
    swolf: string | null;
  }>;
  analysis: {
    version: string;
    parser_version: string;
    quality: "complete" | "partial" | "poor";
    metrics: Record<string, string | number | boolean | null>;
    flags: string[];
  } | null;
  match: { planned_workout_id: string; method: string; confidence: string } | null;
  feedback: {
    id: string;
    rpe: number;
    technique_rating: number | null;
    fatigue_rating: number | null;
    enjoyment_rating: number | null;
    pain_present: boolean;
    pain_location: string | null;
    pain_intensity: number | null;
    comment: string | null;
    version: number;
    updated_at: string;
  } | null;
  raw_fit_exposed: false;
}

export interface GarminSyncRun {
  id: string;
  status: "running" | "succeeded" | "partial" | "failed" | "cancelled";
  trigger: string;
  listed: number;
  created: number;
  updated: number;
  skipped: number;
  failed: number;
  started_at: string;
  finished_at: string | null;
  error_code: string | null;
}

export interface GarminSyncJob {
  id: string;
  status: "QUEUED" | "LEASED" | "RUNNING" | "SUCCEEDED" | "RETRY_SCHEDULED" | "FAILED_TERMINAL" | "NEEDS_RECONCILIATION";
}

export interface OperationsJob {
  id: string;
  job_type: string;
  status: GarminSyncJob["status"];
  attempts: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  error_code: string | null;
  retryable: boolean;
}

export interface OperationsSnapshot {
  jobs: OperationsJob[];
  metrics: {
    counts: Record<string, number>;
    oldest_active_age_seconds: number;
    dead_count: number;
  };
}

export interface AppNotification {
  id: string;
  notification_type: string;
  title: string;
  body: string;
  link: string | null;
  read_at: string | null;
  created_at: string;
}

export interface DataExport {
  id: string;
  status: "PENDING" | "READY" | "EXPIRED" | "FAILED";
  checksum: string | null;
  size_bytes: number | null;
  expires_at: string | null;
  download_url: string | null;
}

export interface DeletionRequest {
  id: string;
  status: "REQUESTED" | "CONFIRMED" | "EXECUTED" | "CANCELLED";
  execute_after: string;
  confirmation_phrase: string | null;
}

export type WorkoutPurpose = "TECHNIQUE" | "BASE" | "ENDURANCE" | "THRESHOLD" | "SPEED" | "RECOVERY" | "TEST" | "MIXED";
export type WorkoutRole = "WARMUP" | "WORK" | "RECOVERY" | "REST" | "COOLDOWN" | "DRILL" | "OTHER";

export interface WorkoutStep {
  type: "step";
  id?: string;
  label?: string | null;
  step_role?: WorkoutRole;
  end_condition: { type: "distance"; meters: number } | { type: "time"; seconds: number } | { type: "lap_button" };
  target?: { type: "none" } | { type: "rpe"; min: number; max: number } | { type: "pace_range"; min_seconds_per_100m: number; max_seconds_per_100m: number } | { type: "zone"; zone: string };
  stroke?: { type: "freestyle" | "backstroke" | "breaststroke" | "butterfly" | "mixed" | "choice" | "kick" } | { type: "drill"; drill: string; side?: "LEFT" | "RIGHT" | "ALTERNATE" | null };
  intensity?: "EASY" | "MODERATE" | "TEMPO" | "THRESHOLD" | "FAST" | "MAX" | "CUSTOM" | null;
  equipment?: Array<"BOARD" | "FINS" | "PADDLES" | "PULL_BUOY" | "SNORKEL" | "NONE">;
  instructions?: string | null;
}

export interface WorkoutRepeat {
  type: "repeat";
  id?: string;
  label?: string | null;
  repetitions: number;
  children: WorkoutNode[];
}

export type WorkoutNode = WorkoutStep | WorkoutRepeat;

export interface CanonicalWorkout {
  schema_version: "1.0";
  title: string;
  description?: string | null;
  sport: "POOL_SWIMMING";
  pool_length_m: number;
  purpose: WorkoutPurpose;
  tags?: string[];
  nodes: WorkoutNode[];
}

export interface WorkoutValidationIssue { code: string; path: string; message: string; }
export interface WorkoutValidation {
  valid: boolean;
  errors: WorkoutValidationIssue[];
  warnings: WorkoutValidationIssue[];
  totals: { distance_m: number; distance_steps: number; executable_steps: number; lengths: number; active_seconds: number; rest_seconds: number; estimated_total_seconds: number; };
}

export interface WorkoutRevision {
  id: string;
  revision_number: number;
  definition: CanonicalWorkout;
  validation: WorkoutValidation;
  content_hash: string;
  change_reason: string | null;
  created_at: string;
}

export interface Workout {
  id: string;
  title: string;
  purpose: WorkoutPurpose;
  pool_id: string;
  status: "draft" | "approved" | "scheduled" | "published" | "completed" | "cancelled" | "archived";
  version: number;
  current_revision_id: string;
  approved_revision_id: string | null;
  current_revision: WorkoutRevision;
  revisions: WorkoutRevision[];
  schedule: { id: string; scheduled_date: string; scheduled_start_time: string | null; timezone: string; pool_id: string } | null;
}

export interface WorkoutSaveResult {
  workout: Workout;
  garmin: {
    status: string;
    job_id: string | null;
    scheduled_date: string;
    replayed: boolean;
    warnings: string[];
  } | null;
}

export interface WorkoutDeleteResult {
  status: "ACCEPTED";
  workout_id: string;
  local_removed: boolean;
  calendar_removed: boolean;
  garmin_cleanup: "QUEUED" | "COMPLETED" | "NEEDS_ATTENTION";
  job_id: string;
  replayed: boolean;
}
