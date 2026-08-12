import type {
  AuthConfig,
  AvailabilityRule,
  Goal,
  GarminConnection,
  GarminDevice,
  GarminSyncJob,
  GarminSyncRun,
  Me,
  Pool,
  ProblemDetail,
  SwimActivity,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: ProblemDetail,
  ) {
    super(problem.detail);
  }
}

function csrfToken(): string | undefined {
  return document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith("swim_coach_csrf="))
    ?.split("=", 2)[1];
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) {
    headers.set("Content-Type", "application/json");
  }
  if (init.method && !["GET", "HEAD"].includes(init.method)) {
    const token = csrfToken();
    if (token) headers.set("X-CSRF-Token", decodeURIComponent(token));
  }
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    credentials: "include",
    headers,
  });
  if (!response.ok) {
    const problem = (await response.json()) as ProblemDetail;
    throw new ApiError(response.status, problem);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  authConfig: () => request<AuthConfig>("/auth/config"),
  me: () => request<Me>("/me"),
  devLogin: () => request<void>("/auth/dev-login", { method: "POST" }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  updateProfile: (payload: {
    display_name: string;
    locale: string;
    timezone: string;
    experience_level: string;
    default_sessions_per_week: number;
    version: number;
  }) => request<Me>("/me/profile", { method: "PATCH", body: JSON.stringify(payload) }),
  pools: () => request<Pool[]>("/pools"),
  createPool: (payload: {
    name: string;
    length_m: number;
    is_default: boolean;
    location_label: string | null;
  }) =>
    request<Pool>("/pools", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(payload),
    }),
  availability: () => request<AvailabilityRule[]>("/availability"),
  replaceAvailability: (rules: Array<Omit<AvailabilityRule, "id" | "version">>) =>
    request<AvailabilityRule[]>("/availability", {
      method: "PUT",
      body: JSON.stringify({ rules }),
    }),
  goals: () => request<Goal[]>("/goals"),
  updateGoal: (goal: Goal) =>
    request<Goal>(`/goals/${goal.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: goal.title,
        status: goal.status,
        priority: goal.priority,
        target_distance_m: goal.target_distance_m,
        target_duration_seconds: goal.target_duration_seconds,
        target_date: goal.target_date,
        version: goal.version,
      }),
    }),
  garminConnection: () => request<GarminConnection>("/integrations/garmin"),
  garminDevices: () => request<GarminDevice[]>("/integrations/garmin/devices"),
  garminActivities: () => request<SwimActivity[]>("/integrations/garmin/activities"),
  garminSyncRuns: () => request<GarminSyncRun[]>("/integrations/garmin/sync-runs"),
  requestGarminSync: () =>
    request<GarminSyncJob>("/integrations/garmin/sync", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
  disconnectGarmin: () =>
    request<GarminConnection>("/integrations/garmin", { method: "DELETE" }),
};
