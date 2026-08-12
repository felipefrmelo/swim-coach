import { expect, test } from "@playwright/test";

const activity = {
  id: "00000000-0000-0000-0000-000000000303",
  name: "Natação em piscina",
  subtype: "lap_swimming",
  start_time_utc: "2026-08-12T10:00:00Z",
  distance_m: 120,
  elapsed_seconds: "190",
  pool_length_m: 20,
  length_count: 6,
  avg_hr: 138,
  avg_swolf: "46",
};

const detail = {
  activity,
  normalized: true,
  parser_version: "garmin-fit-sdk:21.208.0|swim-coach:1.0.0",
  profile_version: "21.208.0",
  quality: "complete",
  completeness: "1.000",
  warnings: [],
  intervals: [
    { index: 0, interval_type: "work", distance_m: 60, duration_seconds: "87", rest_seconds: "5", pace_seconds_per_100m: "145", stroke_type: "freestyle", swolf: "46" },
    { index: 1, interval_type: "work", distance_m: 60, duration_seconds: "93", rest_seconds: "5", pace_seconds_per_100m: "155", stroke_type: "freestyle", swolf: "48" },
  ],
  analysis: {
    version: "swim-analysis:1.0.0|feedback:0",
    parser_version: "garmin-fit-sdk:21.208.0|swim-coach:1.0.0",
    quality: "complete",
    metrics: { average_pace_seconds_per_100m: "150", consistency_cv: "0.047", total_rest_seconds: "10", fade_percent: "6.90", average_swolf: "47" },
    flags: [],
  },
  match: null,
  feedback: null,
  raw_fit_exposed: false,
};

test("athlete reviews normalized intervals and records non-diagnostic feedback", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Entrar no ambiente local" }).click();

  await page.route("**/api/v1/activities**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "PUT" && path.endsWith("/feedback")) {
      await route.fulfill({
        json: {
          id: "00000000-0000-0000-0000-000000000304",
          rpe: 6,
          technique_rating: 4,
          fatigue_rating: null,
          enjoyment_rating: null,
          pain_present: false,
          pain_location: null,
          pain_intensity: null,
          comment: null,
          version: 1,
          updated_at: "2026-08-12T10:05:00Z",
        },
      });
      return;
    }
    await route.fulfill({ json: path.endsWith(activity.id) ? detail : [activity] });
  });

  await page.getByRole("link", { name: "Atividades" }).click();
  await expect(page.getByRole("heading", { name: "Atividades" })).toBeVisible();
  await page.getByRole("link", { name: /Natação em piscina/ }).click();

  await expect(page.getByRole("heading", { name: "Natação em piscina" })).toBeVisible();
  await expect(page.getByText("Qualidade alta")).toBeVisible();
  await expect(page.getByText("60 m · Livre")).toHaveCount(2);
  await expect(page.getByText(/FIT bruto e payload Garmin não são retornados/)).toBeVisible();
  await expect(page.getByText(/não são diagnóstico médico/)).toBeVisible();

  await page.getByRole("button", { name: "6" }).first().click();
  await page.getByRole("button", { name: "4" }).last().click();
  await page.getByRole("button", { name: "Salvar feedback" }).click();
  await expect(page.getByText("Feedback salvo e análise versionada.")).toBeVisible();

  if (process.env.P03_EVIDENCE_SCREENSHOT) {
    await page.screenshot({ path: process.env.P03_EVIDENCE_SCREENSHOT, fullPage: true });
  }
});
