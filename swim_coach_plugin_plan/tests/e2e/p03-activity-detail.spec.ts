import { expect, test } from "@playwright/test";

const activity = {
  activity_id: "00000000-0000-0000-0000-000000000303",
  name: "Natação em piscina",
  subtype: "lap_swimming",
  started_at_utc: "2026-08-12T12:00:00Z",
  started_at_local: "2026-08-12T09:00:00-03:00",
  timezone: "America/Sao_Paulo",
  distance_m: 120,
  durations: {
    elapsed_s: "190",
    timer_s: "180",
    moving_s: "170",
    swim_s: "168",
    rest_s: "10",
    stationary_s: "2",
  },
  speeds: { garmin_reported_m_per_s: "0.704225" },
  paces: {
    pace_from_garmin_reported_speed_s_per_100m: "142",
    moving_s_per_100m: "141.667",
    swim_s_per_100m: "140",
    timer_s_per_100m: "150",
    session_s_per_100m: "158.333",
  },
  pool: { length_m: 20, active_length_count: 6 },
  provenance: { pool_length_m: { source: "GARMIN" } },
  data_quality: { level: "HIGH", reasons: [] },
  session_evaluation: {
    garmin: { rpe: "3.0", feeling_score: 75 },
    manual_override: { rpe: null, feeling_score: null },
    effective: { rpe: "3.0", feeling_score: 75 },
    provenance: {
      rpe: { source: "GARMIN", raw_field: "session.workout_rpe", transformation: "divide FIT Borg CR10 score by 10", interpretation: "documented" },
      feeling_score: { source: "GARMIN", raw_field: "session.workout_feel", transformation: "preserve FIT 0-100 workout feeling score", interpretation: "documented" },
    },
  },
};

const detail = {
  ...activity,
  schema_version: "2.0",
  normalization: {
    parser_version: "garmin-fit-sdk:21.208.0|swim-coach:2.1.0",
    profile_version: "garmin-fit-profile:21.208.0",
    completeness: "1.000",
    warnings: [],
  },
  intervals: [
    {
      index: 0,
      interval_type: "SWIM",
      planned_role: "WORK",
      distance_m: 60,
      durations: { elapsed_s: "92", timer_s: "87", moving_s: "84", swim_s: "84", rest_s: "0", stationary_s: "3" },
      speeds: { garmin_reported_m_per_s: "0.724638" },
      paces: { pace_from_garmin_reported_speed_s_per_100m: "138", moving_s_per_100m: "140", swim_s_per_100m: "140", timer_s_per_100m: "145", elapsed_s_per_100m: "153.333" },
      detected_stroke: "freestyle",
      planned_stroke: "freestyle",
      stroke_count: 30,
      stroke_rate: "32",
      swolf: "46",
      provenance: {},
      quality_warnings: [],
    },
    {
      index: 1,
      interval_type: "SWIM",
      planned_role: "WORK",
      distance_m: 60,
      durations: { elapsed_s: "98", timer_s: "93", moving_s: "86", swim_s: "84", rest_s: "0", stationary_s: "7" },
      speeds: { garmin_reported_m_per_s: "0.704225" },
      paces: { pace_from_garmin_reported_speed_s_per_100m: "142", moving_s_per_100m: "143.333", swim_s_per_100m: "140", timer_s_per_100m: "155", elapsed_s_per_100m: "163.333" },
      detected_stroke: "freestyle",
      planned_stroke: "freestyle",
      stroke_count: 31,
      stroke_rate: "31",
      swolf: "48",
      provenance: {},
      quality_warnings: [],
    },
  ],
  lengths: [],
  analysis: {
    version: "swim-analysis:2.0.0|fb:0",
    quality: "complete",
    metrics: {
      consistency_cv: "0.012",
      total_rest_seconds: "10",
      fade_percent: "2.38",
      stroke_efficiency: [{ stroke: "freestyle", average_swolf: "47" }],
    },
    flags: [],
    summary: {},
  },
  match: null,
  feedback: null,
  raw_fit_exposed: false,
};

test("athlete reviews normalized intervals and records non-diagnostic feedback", async ({ page }) => {
  await page.route("**/api/v*/activities**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "PUT" && path.endsWith("/feedback")) {
      await route.fulfill({
        json: {
          id: "00000000-0000-0000-0000-000000000304",
          rpe: 6,
          feeling_score: null,
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
    await route.fulfill({ json: path.endsWith(activity.activity_id) ? detail : [activity] });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Entrar no ambiente local" }).click();

  await page.getByRole("link", { name: "Atividades" }).click();
  await expect(page.getByRole("heading", { name: "Atividades" })).toBeVisible();
  await page.getByRole("link", { name: /Natação em piscina/ }).click();

  await expect(page.getByRole("heading", { name: "Natação em piscina" })).toBeVisible();
  await expect(page.getByText("Ritmo nadando (moving)")).toBeVisible();
  await expect(page.getByText("Ritmo da sessão (elapsed)")).toBeVisible();
  await expect(page.getByText("Qualidade alta")).toBeVisible();
  await expect(page.getByText("60 m · livre")).toHaveCount(2);
  await expect(page.getByText(/FIT bruto e payload Garmin não são retornados/)).toBeVisible();
  await expect(page.getByText(/não são diagnóstico médico/)).toBeVisible();
  await expect(page.getByText("Importado do Garmin: RPE 3/10 · sensação 75/100")).toBeVisible();

  await page.getByRole("button", { name: "Ajustar RPE" }).click();
  await page.getByRole("button", { name: "6" }).first().click();
  await page.getByRole("button", { name: "4" }).last().click();
  await page.getByRole("button", { name: "Salvar feedback" }).click();
  await expect(page.getByText("Feedback salvo e análise versionada.")).toBeVisible();

  if (process.env.P03_EVIDENCE_SCREENSHOT) {
    await page.screenshot({ path: process.env.P03_EVIDENCE_SCREENSHOT, fullPage: true });
  }
});
