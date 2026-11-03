import { expect, test } from "@playwright/test";

test("current goal and calendar preview preserve a workout identity", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Entrar no ambiente local" }).click();
  await expect(page.getByRole("heading", { name: "Seu ponto de partida" })).toBeVisible();
  const csrf = (await page.context().cookies()).find((c) => c.name === "swim_coach_csrf")?.value;
  expect(csrf).toBeTruthy();
  const headers = { "X-CSRF-Token": decodeURIComponent(csrf!) };
  const pools = await (await page.request.get("/api/v1/pools")).json();
  const goals = await (await page.request.get("/api/v1/goals")).json();
  const goal = goals.find((g: { status: string }) => g.status === "active");
  const goalResult = await page.request.patch(`/api/v1/goals/${goal.id}`, { headers,
    data: { title: "Meta sintética vigente", target_distance_m: 1000, target_duration_seconds: "1380", target_date: null, priority: 0, status: "active", version: goal.version } });
  expect(goalResult.ok()).toBeTruthy();
  const availability = await page.request.put("/api/v1/availability", { headers,
    data: { rules: [{ day_of_week: 1, start_local_time: "06:15:00", end_local_time: "07:00:00", max_duration_minutes: 45, pool_id: pools[0].id }] } });
  expect(availability.ok()).toBeTruthy();
  const day = new Date();
  const offset = (2 - day.getDay() + 7) % 7 || 7;
  day.setDate(day.getDate() + offset);
  const original = day.toISOString().slice(0, 10);
  day.setDate(day.getDate() + 7);
  const target = day.toISOString().slice(0, 10);
  const saved = await page.request.post("/api/v1/workouts/save", { headers, data: {
    pool_id: pools[0].id, scheduled_date: original, scheduled_start_time: "06:15:00", publish_to_garmin: false,
    definition: { title: "Sessão sintética de calendário", sport: "POOL_SWIMMING", pool_length_m: 20, purpose: "BASE",
      nodes: [{ type: "step", step_role: "WORK", end_condition: { type: "distance", meters: 1000 }, target: { type: "pace_range", min_seconds_per_100m: 165, max_seconds_per_100m: 195 } }] }
  } });
  expect(saved.ok()).toBeTruthy();
  const workoutId = (await saved.json()).workout.id;
  await page.reload();
  await expect(page.getByText("Meta em 23 minutos")).toBeVisible();
  await page.getByLabel("Nova data para Sessão sintética de calendário").fill(target);
  await page.getByRole("button", { name: "Prévia do reagendamento" }).click();
  await expect(page.getByRole("button", { name: "Confirmar reagendamento" })).toBeEnabled();
  await page.getByRole("button", { name: "Confirmar reagendamento" }).click();
  await expect(page.getByText("Data local atualizada. Acompanhe a confirmação do Garmin.")).toBeVisible();
  const overview = await (await page.request.get("/api/v1/coaching/overview")).json();
  const matched = overview.agenda.filter((w: { workout_id: string }) => w.workout_id === workoutId);
  expect(matched).toHaveLength(1);
  expect(matched[0].scheduled_date).toBe(target);
  const status = await (await page.request.post("/api/v1/coaching/publication-status", { headers, data: [workoutId] })).json();
  expect(status.items[0].state).toBe("NOT_PUBLISHED");
  expect(status.items[0].remote_confirmed).toBe(false);
});
