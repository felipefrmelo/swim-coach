import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { Me, SwimActivityDetailV2, SwimActivityV2 } from "../api/types";
import { App } from "../app/App";
import { router } from "./router";

const activityId = "00000000-0000-0000-0000-000000000860";
const me: Me = {
  user: {
    id: "00000000-0000-0000-0000-000000000001",
    email: "swimmer@example.test",
    display_name: "Nadador",
    locale: "pt-BR",
    timezone: "America/Sao_Paulo",
    version: 1,
  },
  profile: {
    experience_level: "recreational",
    default_sessions_per_week: 3,
    preferred_distance_unit: "m",
    default_pool_id: "00000000-0000-0000-0000-000000000002",
    version: 1,
  },
};

const activity = {
  activity_id: activityId,
  name: "Natação na piscina",
  subtype: "lap_swimming",
  started_at_utc: "2000-07-01T12:00:00+00:00",
  started_at_local: "2000-07-01T09:00:00-03:00",
  timezone: "America/Sao_Paulo",
  distance_m: 860,
  durations: {
    elapsed_s: "2089.629",
    timer_s: "2075.559",
    moving_s: null,
    swim_s: "1699.541",
    rest_s: "376.018",
    stationary_s: null,
  },
  speeds: { garmin_reported_m_per_s: "0.506" },
  paces: {
    pace_from_garmin_reported_speed_s_per_100m: "197.628",
    moving_s_per_100m: null,
    swim_s_per_100m: "197.621",
    timer_s_per_100m: "241.344",
    session_s_per_100m: "242.980",
  },
  pool: { length_m: 20, active_length_count: 43 },
  provenance: { pool_length_m: { source: "GARMIN" } },
  data_quality: { level: "MEDIUM", reasons: ["PACE_FROM_GARMIN_REPORTED_SPEED_DIFFERS_FROM_TIMER_PACE"] },
} satisfies SwimActivityV2;

const detail = {
  ...activity,
  schema_version: "2.0",
  normalization: {
    parser_version: "garmin-fit-sdk:21.208.0|swim-coach:2.0.4",
    profile_version: "garmin-fit-profile:21.208.0",
    completeness: "0.98",
    warnings: ["PACE_FROM_GARMIN_REPORTED_SPEED_DIFFERS_FROM_TIMER_PACE"],
  },
  intervals: [
    {
      index: 0,
      interval_type: "SWIM",
      planned_role: "WORK",
      distance_m: 80,
      durations: {
        elapsed_s: "158.171",
        timer_s: "158.171",
        moving_s: null,
        swim_s: "135.171",
        rest_s: "23.000",
        stationary_s: null,
      },
      speeds: { garmin_reported_m_per_s: "0.592" },
      paces: {
        pace_from_garmin_reported_speed_s_per_100m: "168.919",
        moving_s_per_100m: null,
        swim_s_per_100m: "168.964",
        timer_s_per_100m: "197.714",
        elapsed_s_per_100m: "197.714",
      },
      detected_stroke: "freestyle",
      planned_stroke: "freestyle",
      stroke_count: 40,
      stroke_rate: "30.0",
      swolf: "49.0",
      provenance: {},
      quality_warnings: [],
    },
    {
      index: 1,
      interval_type: "REST",
      planned_role: "REST",
      distance_m: 0,
      durations: {
        elapsed_s: "25.028",
        timer_s: "25.028",
        moving_s: "0",
        swim_s: "0",
        rest_s: "25.028",
        stationary_s: "25.028",
      },
      speeds: { garmin_reported_m_per_s: null },
      paces: {
        pace_from_garmin_reported_speed_s_per_100m: null,
        moving_s_per_100m: null,
        swim_s_per_100m: null,
        timer_s_per_100m: null,
        elapsed_s_per_100m: null,
      },
      detected_stroke: null,
      planned_stroke: null,
      stroke_count: null,
      stroke_rate: null,
      swolf: null,
      provenance: {},
      quality_warnings: [],
    },
  ],
  lengths: [],
  analysis: null,
  match: null,
  feedback: null,
  raw_fit_exposed: false,
} satisfies SwimActivityDetailV2;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("activity v2 client and pages", () => {
  it("requests the versioned activity collection instead of the legacy endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([activity]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.activities()).resolves.toEqual([activity]);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v2/activities",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/v1/activities",
      expect.anything(),
    );
  });

  it("keeps activity processing and feedback on the versioned resource", async () => {
    document.cookie = "swim_coach_csrf=test-token";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "job-id", status: "QUEUED" }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "feedback-id", rpe: 6 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await api.processActivity(activityId);
    await api.saveFeedback(activityId, "feedback-key", {
      rpe: 6,
      technique_rating: null,
      fatigue_rating: null,
      enjoyment_rating: null,
      pain_present: false,
      pain_location: null,
      pain_intensity: null,
      comment: null,
      version: null,
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(`/api/v2/activities/${activityId}/process`);
    expect(fetchMock.mock.calls[1]?.[0]).toBe(`/api/v2/activities/${activityId}/feedback`);
    for (const [, init] of fetchMock.mock.calls) {
      expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("test-token");
    }
  });

  it("renders the canonical local time, 20 m pool and explicit elapsed duration", async () => {
    vi.spyOn(api, "authConfig").mockResolvedValue({
      oidc_enabled: false,
      dev_auth_enabled: true,
    });
    vi.spyOn(api, "me").mockResolvedValue(me);
    vi.spyOn(api, "activities").mockResolvedValue([activity]);

    render(<App />);
    await router.navigate({ to: "/activities" });

    expect(await screen.findByRole("heading", { name: "Atividades" })).toBeVisible();
    expect(screen.getByText("Natação na piscina")).toBeVisible();
    expect(screen.getByText(/20 m/)).toBeVisible();
    expect(screen.getByText("860 m")).toBeVisible();
    expect(screen.getByText("34min 50s")).toBeVisible();
    expect(api.activities).toHaveBeenCalledOnce();
  });

  it("renders started_at_local in the athlete timezone, not the browser timezone", async () => {
    vi.spyOn(api, "authConfig").mockResolvedValue({
      oidc_enabled: false,
      dev_auth_enabled: true,
    });
    vi.spyOn(api, "me").mockResolvedValue(me);
    vi.spyOn(api, "activities").mockResolvedValue([
      {
        ...activity,
        started_at_local: "2000-07-01T02:00:00-10:00",
        timezone: "Pacific/Honolulu",
      },
    ]);

    render(<App />);
    await router.navigate({ to: "/activities" });

    expect(await screen.findByText(/02:00/)).toBeVisible();
  });

  it("does not invent a 20 m pool when the canonical fact is missing", async () => {
    vi.spyOn(api, "authConfig").mockResolvedValue({
      oidc_enabled: false,
      dev_auth_enabled: true,
    });
    vi.spyOn(api, "me").mockResolvedValue(me);
    vi.spyOn(api, "activities").mockResolvedValue([
      { ...activity, pool: { length_m: null, active_length_count: null } },
    ]);

    render(<App />);
    await router.navigate({ to: "/activities" });

    expect(await screen.findByText(/piscina desconhecida/)).toBeVisible();
    expect(screen.queryByText(/piscina de 20 m/)).not.toBeInTheDocument();
  });

  it("labels swimming pace separately and never presents timer pace as that value", async () => {
    vi.spyOn(api, "authConfig").mockResolvedValue({
      oidc_enabled: false,
      dev_auth_enabled: true,
    });
    vi.spyOn(api, "me").mockResolvedValue(me);
    vi.spyOn(api, "activity").mockResolvedValue(detail);

    render(<App />);
    await router.navigate({
      to: "/activities/$activityId",
      params: { activityId },
    });

    expect(await screen.findByRole("heading", { name: "Natação na piscina" })).toBeVisible();
    expect(screen.getByText("Ritmo por extensões ativas")).toBeVisible();
    expect(screen.getByText("3:18/100m")).toBeVisible();
    expect(screen.getByText("Ritmo nadando (moving)")).toBeVisible();
    expect(screen.getByText("2:49/100m · extensões")).toBeVisible();
    expect(screen.getByText("Ritmo da sessão (elapsed)")).toBeVisible();
    expect(screen.getByText("4:03/100m")).toBeVisible();
    expect(screen.queryByText("4:01/100m")).not.toBeInTheDocument();
    expect(screen.getByText("Descanso")).toBeVisible();
    expect(
      screen.getByText(/FIT bruto e payload Garmin não são retornados por esta API/),
    ).toBeVisible();
  });

  it("prefers freestyle WORK efficiency over drill SWOLF", async () => {
    vi.spyOn(api, "authConfig").mockResolvedValue({
      oidc_enabled: false,
      dev_auth_enabled: true,
    });
    vi.spyOn(api, "me").mockResolvedValue(me);
    vi.spyOn(api, "activity").mockResolvedValue({
      ...detail,
      analysis: {
        version: "activity-analysis:2.0.0",
        quality: "partial",
        flags: [],
        summary: {},
        metrics: {
          stroke_efficiency: [
            {
              stroke: "freestyle",
              planned_role: "DRILL",
              average_swolf: "70.0",
            },
            {
              stroke: "freestyle",
              planned_role: "WORK",
              average_swolf: "42.0",
            },
          ],
        },
      },
    });

    render(<App />);
    await router.navigate({
      to: "/activities/$activityId",
      params: { activityId },
    });

    expect(await screen.findByText("42.0")).toBeVisible();
    expect(screen.queryByText("70.0")).not.toBeInTheDocument();
  });

  it("shows a zero-distance UNKNOWN step as contextual rest when planning matched REST", async () => {
    vi.spyOn(api, "authConfig").mockResolvedValue({
      oidc_enabled: false,
      dev_auth_enabled: true,
    });
    vi.spyOn(api, "me").mockResolvedValue(me);
    vi.spyOn(api, "activity").mockResolvedValue({
      ...detail,
      intervals: [
        {
          ...detail.intervals[1],
          interval_type: "UNKNOWN",
          planned_role: "REST",
          durations: { ...detail.intervals[1].durations, rest_s: "0" },
        },
      ],
    });

    render(<App />);
    await router.navigate({
      to: "/activities/$activityId",
      params: { activityId },
    });

    expect(await screen.findByText("Descanso planejado · tipo detectado incerto")).toBeVisible();
    expect(screen.getByText(/25s descanso contextual do planejamento/)).toBeVisible();
  });

  it("keeps FIT IDLE rest explicit when analysis does not need planned context", async () => {
    vi.spyOn(api, "authConfig").mockResolvedValue({
      oidc_enabled: false,
      dev_auth_enabled: true,
    });
    vi.spyOn(api, "me").mockResolvedValue(me);
    vi.spyOn(api, "activity").mockResolvedValue({
      ...detail,
      durations: {
        ...detail.durations,
        moving_s: null,
        swim_s: "1699.541",
        rest_s: "376.018",
        stationary_s: null,
      },
      analysis: {
        version: "swim-analysis:2.0.2",
        quality: "partial",
        flags: [],
        summary: {},
        metrics: {
          durations: { rest_s: "376.018" },
          sets: [],
        },
      },
    });

    render(<App />);
    await router.navigate({
      to: "/activities/$activityId",
      params: { activityId },
    });

    expect(await screen.findByText("Descanso explícito")).toBeVisible();
    expect(screen.getByText("6min 16s")).toBeVisible();
    expect(screen.getByText(/extensões IDLE no FIT normalizado/)).toBeVisible();
    expect(screen.queryByText("Descanso contextual")).not.toBeInTheDocument();
  });

  it("does not use a drill set as representative consistency or fade", async () => {
    vi.spyOn(api, "authConfig").mockResolvedValue({
      oidc_enabled: false,
      dev_auth_enabled: true,
    });
    vi.spyOn(api, "me").mockResolvedValue(me);
    vi.spyOn(api, "activity").mockResolvedValue({
      ...detail,
      analysis: {
        version: "swim-analysis:2.0.2",
        quality: "partial",
        flags: ["REST_CLASSIFIED_FROM_PLANNED_WORKOUT"],
        summary: {},
        metrics: {
          durations: { rest_s: "150" },
          sets: [
            {
              key: { stroke: "FREESTYLE", planned_role: "DRILL", distance_m: 40 },
              coefficient_of_variation: "0.050",
              fade_percent: "10.0",
            },
          ],
        },
      },
    });

    render(<App />);
    await router.navigate({
      to: "/activities/$activityId",
      params: { activityId },
    });

    expect(await screen.findByText("Consistência")).toBeVisible();
    expect(screen.getByText("Descanso contextual")).toBeVisible();
    expect(screen.getByText("2min 30s")).toBeVisible();
    expect(screen.queryByText("5.0%")).not.toBeInTheDocument();
    expect(screen.queryByText("+10.0%")).not.toBeInTheDocument();
  });
});
