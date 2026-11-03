import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { CoachingOverview } from "../api/types";
import { CoachingPanel } from "./coaching";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("distinguishes an ended historical cycle, an ad-hoc session and a queued Garmin job", async () => {
  const data: CoachingOverview = {
    account: { account_ref: "synthetic", display_name: "Swimmer" }, timezone: "America/Sao_Paulo", local_date: "2026-11-02",
    current_goal: { title: "1000 m", distance_m: 1000, duration_seconds: 1380, pace_seconds_per_100m: 138, version: 1 },
    cycles: [{ plan_id: "cycle", title: "Historical 2000 m", lifecycle_state: "ENDED_NEEDS_REVIEW", status: "ACTIVE", goal_relationship: "PREVIOUS_OR_UNVERIFIED", predecessor_plan_id: null }],
    agenda: [{ workout_id: "workout", title: "Retomada", version: 2, scheduled_date: "2026-11-03", scheduled_start_time: "06:15", pool_length_m: 20, distance_m: 1040, completed: false, provenance: "CONTINGENCY" }],
    next_workout: null, pending_jobs: [{ job_id: "job", state: "QUEUED", type: "workout.upsert_garmin", updated_at: "2026-11-02T12:00:00Z" }],
  };
  vi.spyOn(api, "coachingOverview").mockResolvedValue(data);
  vi.spyOn(api, "coachingPublication").mockResolvedValue({ items: [{ workout_id: "workout", state: "QUEUED", remote_confirmed: false, local_date: "2026-11-03", remote_date: null, last_verified_at: null }], all_published: false });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><CoachingPanel /></QueryClientProvider>);
  expect(await screen.findByText("Encerrado aguardando decisão")).toBeVisible();
  expect(await screen.findByText("Na fila do Garmin")).toBeVisible();
  expect(screen.getByText("Retomada avulsa aguardando decisão sobre ciclo")).toBeVisible();
  expect(screen.getByText(/03\/11\/2026.*06:15/)).toBeVisible();
  expect(screen.queryByText("Garmin confirmado")).not.toBeInTheDocument();
});
