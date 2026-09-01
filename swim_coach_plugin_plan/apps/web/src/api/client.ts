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
  SwimActivityDetail,
  SwimActivityV2,
  SwimActivityDetailV2,
  CanonicalWorkout,
  Workout,
  WorkoutSaveResult,
  WorkoutDeleteResult,
  WorkoutValidation,
  OperationsSnapshot,
  OperationsJob,
  AppNotification,
  DataExport,
  DeletionRequest,
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

async function requestV2<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (init.method && !["GET", "HEAD"].includes(init.method)) {
    const token = csrfToken();
    if (token) headers.set("X-CSRF-Token", decodeURIComponent(token));
  }
  const response = await fetch(`/api/v2${path}`, { ...init, credentials: "include", headers });
  if (!response.ok) {
    const problem = (await response.json()) as ProblemDetail;
    throw new ApiError(response.status, problem);
  }
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
  activities: () => requestV2<SwimActivityV2[]>("/activities"),
  activity: (id: string) => requestV2<SwimActivityDetailV2>(`/activities/${id}`),
  processActivity: (id: string) =>
    requestV2<GarminSyncJob>(`/activities/${id}/process`, {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
  saveFeedback: (
    id: string,
    idempotencyKey: string,
    payload: {
      rpe: number;
      technique_rating: number | null;
      fatigue_rating: number | null;
      enjoyment_rating: number | null;
      pain_present: boolean;
      pain_location: string | null;
      pain_intensity: number | null;
      comment: string | null;
      version: number | null;
    },
  ) => requestV2<SwimActivityDetail["feedback"]>(`/activities/${id}/feedback`, {
    method: "PUT",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(payload),
  }),
  garminSyncRuns: () => request<GarminSyncRun[]>("/integrations/garmin/sync-runs"),
  requestGarminSync: () =>
    request<GarminSyncJob>("/integrations/garmin/sync", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
  operations: () => request<OperationsSnapshot>("/operations"),
  retryJob: (id: string) => request<OperationsJob>(`/operations/jobs/${id}/retry`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  }),
  notifications: () => request<AppNotification[]>("/operations/notifications"),
  readNotification: (id: string) => request<AppNotification>(`/operations/notifications/${id}/read`, { method: "POST" }),
  createDataExport: () => request<DataExport>("/privacy/exports", {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  }),
  requestDeletion: () => request<DeletionRequest>("/privacy/deletion-requests", {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  }),
  confirmDeletion: (id: string, confirmation: string) => request<DeletionRequest>(`/privacy/deletion-requests/${id}/confirm`, {
    method: "POST",
    body: JSON.stringify({ confirmation }),
  }),
  disconnectGarmin: () =>
    request<GarminConnection>("/integrations/garmin", { method: "DELETE" }),
  workouts: () => request<Workout[]>("/workouts"),
  workout: (id: string) => request<Workout>(`/workouts/${id}`),
  deleteWorkout: (id: string) =>
    request<WorkoutDeleteResult>(`/workouts/${id}`, { method: "DELETE" }),
  saveWorkout: (payload: {
    workout_id: string | null;
    pool_id: string;
    definition: CanonicalWorkout;
    scheduled_date: string | null;
    scheduled_start_time: string | null;
    change_reason: string | null;
    publish_to_garmin: boolean;
  }) => request<WorkoutSaveResult>("/workouts/save", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  validateWorkout: (definition: CanonicalWorkout) =>
    request<WorkoutValidation>("/workouts/validate", {
      method: "POST",
      body: JSON.stringify(definition),
    }),
};
