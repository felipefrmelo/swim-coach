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
