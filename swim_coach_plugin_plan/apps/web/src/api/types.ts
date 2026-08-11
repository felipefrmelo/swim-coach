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
