import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CanonicalWorkout, Workout } from "../api/types";
import { App } from "../app/App";
import { router } from "./router";

const poolId = "00000000-0000-0000-0000-000000000002";
const workoutId = "00000000-0000-0000-0000-000000000004";
const me = {
  user: { id: "00000000-0000-0000-0000-000000000001", email: "swimmer@example.test", display_name: "Nadador", locale: "pt-BR", timezone: "America/Sao_Paulo", version: 1 },
  profile: { experience_level: "recreational", default_sessions_per_week: 3, preferred_distance_unit: "m", default_pool_id: poolId, version: 1 },
};

function jsonResponse(value: unknown) {
  return Promise.resolve(new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } }));
}

function savedWorkout(definition: CanonicalWorkout): Workout {
  const validation = {
    valid: true,
    errors: [],
    warnings: [],
    totals: { distance_m: 1600, distance_steps: 14, executable_steps: 15, lengths: 80, active_seconds: 0, rest_seconds: 120, estimated_total_seconds: 120 },
  };
  const revision = {
    id: "00000000-0000-0000-0000-000000000005",
    revision_number: 1,
    definition,
    validation,
    content_hash: "a".repeat(64),
    change_reason: null,
    created_at: "2026-08-26T20:00:00Z",
  };
  return {
    id: workoutId,
    title: definition.title,
    purpose: definition.purpose,
    pool_id: poolId,
    status: "scheduled",
    version: 1,
    current_revision_id: revision.id,
    approved_revision_id: revision.id,
    current_revision: revision,
    revisions: [revision],
    schedule: { id: "00000000-0000-0000-0000-000000000006", scheduled_date: "2026-08-27", scheduled_start_time: "19:00:00", timezone: "America/Sao_Paulo", pool_id: poolId },
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("workout target and notes editor", () => {
  it("saves and reloads targets and notes for top-level and repeated steps", async () => {
    let persisted: Workout | undefined;
    let submitted: CanonicalWorkout | undefined;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/auth/config")) return jsonResponse({ oidc_enabled: false, dev_auth_enabled: true });
      if (path.endsWith("/me")) return jsonResponse(me);
      if (path.endsWith("/pools")) return jsonResponse([{ id: poolId, name: "Piscina principal", length_m: 20, is_default: true, location_label: null, active: true, version: 1 }]);
      if (path.endsWith("/workouts/save")) {
        const body = JSON.parse(String(init?.body)) as { definition: CanonicalWorkout };
        submitted = body.definition;
        persisted = savedWorkout(body.definition);
        return jsonResponse({ workout: persisted, garmin: null });
      }
      if (path.endsWith(`/workouts/${workoutId}`) && persisted) return jsonResponse(persisted);
      if (path.endsWith("/workouts")) return jsonResponse([]);
      return jsonResponse([]);
    }));

    const firstRender = render(<App />);
    await router.navigate({ to: "/workouts/new" });
    expect(await screen.findByRole("heading", { name: "Novo treino" })).toBeVisible();

    fireEvent.change(screen.getAllByLabelText("Tipo de meta")[0], { target: { value: "rpe" } });
    fireEvent.change(screen.getByLabelText("RPE mínimo"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("RPE máximo"), { target: { value: "6" } });
    fireEvent.change(screen.getAllByLabelText("Notas")[0], { target: { value: "Respiração bilateral" } });
    expect(screen.getByText(/A Garmin aceita uma categoria de esforço por etapa/)).toBeVisible();

    fireEvent.change(screen.getAllByLabelText("Tipo de meta")[1], { target: { value: "pace_range" } });
    const faster = screen.getByLabelText("Mais rápido (/100 m)");
    const slower = screen.getByLabelText("Mais lento (/100 m)");
    fireEvent.change(faster, { target: { value: "1:40" } });
    fireEvent.blur(faster);
    fireEvent.change(slower, { target: { value: "1:50" } });
    fireEvent.blur(slower);
    fireEvent.change(screen.getAllByLabelText("Notas")[1], { target: { value: "Braçada longa" } });

    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
    expect(await screen.findByRole("heading", { name: "Editar treino" })).toBeVisible();
    await waitFor(() => expect(submitted).toBeDefined());
    expect(submitted?.nodes[0]).toMatchObject({
      target: { type: "rpe", min: 5, max: 6 },
      instructions: "Respiração bilateral",
    });
    const repeat = submitted?.nodes[1];
    expect(repeat?.type).toBe("repeat");
    if (repeat?.type !== "repeat") throw new Error("Expected the starter workout repeat");
    expect(repeat.children[0]).toMatchObject({
      target: { type: "pace_range", min_seconds_per_100m: 100, max_seconds_per_100m: 110 },
      instructions: "Braçada longa",
    });

    firstRender.unmount();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Editar treino" })).toBeVisible();
    expect(screen.getAllByLabelText("Tipo de meta")[0]).toHaveValue("rpe");
    expect(screen.getByLabelText("RPE mínimo")).toHaveValue(5);
    expect(screen.getByLabelText("RPE máximo")).toHaveValue(6);
    expect(screen.getAllByLabelText("Notas")[0]).toHaveValue("Respiração bilateral");
    expect(screen.getAllByLabelText("Tipo de meta")[1]).toHaveValue("pace_range");
    expect(screen.getByLabelText("Mais rápido (/100 m)")).toHaveValue("1:40");
    expect(screen.getByLabelText("Mais lento (/100 m)")).toHaveValue("1:50");
    expect(screen.getAllByLabelText("Notas")[1]).toHaveValue("Braçada longa");
  });

  it("keeps pace drafts attached to id-less steps when they are reordered", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/auth/config")) return jsonResponse({ oidc_enabled: false, dev_auth_enabled: true });
      if (path.endsWith("/me")) return jsonResponse(me);
      if (path.endsWith("/pools")) return jsonResponse([{ id: poolId, name: "Piscina principal", length_m: 20, is_default: true, location_label: null, active: true, version: 1 }]);
      if (path.endsWith("/workouts")) return jsonResponse([]);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await router.navigate({ to: "/workouts/new" });
    expect(await screen.findByRole("heading", { name: "Novo treino" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Etapa" }));
    fireEvent.click(screen.getByRole("button", { name: "Etapa" }));
    const fourth = screen.getByRole("article", { name: "Etapa 4: Nado" });
    const fifth = screen.getByRole("article", { name: "Etapa 5: Nado" });
    fireEvent.change(within(fourth).getByLabelText("Tipo de meta"), { target: { value: "pace_range" } });
    fireEvent.change(within(fifth).getByLabelText("Tipo de meta"), { target: { value: "pace_range" } });
    for (const [article, fast, slow] of [[fourth, "1:40", "1:50"], [fifth, "2:00", "2:10"]] as const) {
      const fastInput = within(article).getByLabelText("Mais rápido (/100 m)");
      const slowInput = within(article).getByLabelText("Mais lento (/100 m)");
      fireEvent.change(fastInput, { target: { value: fast } });
      fireEvent.blur(fastInput);
      fireEvent.change(slowInput, { target: { value: slow } });
      fireEvent.blur(slowInput);
    }

    fireEvent.click(within(fifth).getByRole("button", { name: "Mover para cima" }));
    const movedFourth = screen.getByRole("article", { name: "Etapa 4: Nado" });
    expect(within(movedFourth).getByLabelText("Mais rápido (/100 m)")).toHaveValue("2:00");
    expect(within(movedFourth).getByLabelText("Mais lento (/100 m)")).toHaveValue("2:10");

    const invalidPace = within(movedFourth).getByLabelText("Mais rápido (/100 m)");
    fireEvent.change(invalidPace, { target: { value: "2:99" } });
    fireEvent.blur(invalidPace);
    expect(within(movedFourth).getByRole("alert")).toHaveTextContent("Use minutos e segundos");
    expect(screen.getByRole("button", { name: "Salvar" })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/workouts/save"))).toBe(false);
  });

  it("edits a step below a nested repeat", async () => {
    const nestedDefinition: CanonicalWorkout = {
      schema_version: "1.0",
      title: "Repetição aninhada",
      sport: "POOL_SWIMMING",
      pool_length_m: 20,
      purpose: "TECHNIQUE",
      nodes: [{
        type: "repeat",
        id: "outer",
        repetitions: 2,
        children: [{
          type: "repeat",
          id: "inner",
          repetitions: 2,
          children: [{ type: "step", step_role: "DRILL", end_condition: { type: "distance", meters: 40 }, target: { type: "none" }, stroke: { type: "freestyle" } }],
        }],
      }],
    };
    let persisted = savedWorkout(nestedDefinition);
    let submitted: CanonicalWorkout | undefined;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/auth/config")) return jsonResponse({ oidc_enabled: false, dev_auth_enabled: true });
      if (path.endsWith("/me")) return jsonResponse(me);
      if (path.endsWith(`/workouts/${workoutId}`)) return jsonResponse(persisted);
      if (path.endsWith("/workouts/save")) {
        const body = JSON.parse(String(init?.body)) as { definition: CanonicalWorkout };
        submitted = body.definition;
        persisted = savedWorkout(body.definition);
        return jsonResponse({ workout: persisted, garmin: null });
      }
      if (path.endsWith("/workouts")) return jsonResponse([]);
      return jsonResponse([]);
    }));

    render(<App />);
    await router.navigate({ to: "/workouts/$workoutId", params: { workoutId } });
    expect(await screen.findByRole("heading", { name: "Editar treino" })).toBeVisible();
    expect(await screen.findByDisplayValue("Repetição aninhada")).toBeVisible();
    const nested = await screen.findByRole("region", { name: "Grupo aninhado 1" });
    fireEvent.change(within(nested).getByLabelText("Tipo de meta"), { target: { value: "rpe" } });
    fireEvent.change(within(nested).getByLabelText("RPE mínimo"), { target: { value: "3" } });
    fireEvent.change(within(nested).getByLabelText("RPE máximo"), { target: { value: "4" } });
    fireEvent.change(within(nested).getByLabelText("Notas"), { target: { value: "Cotovelo alto" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(submitted).toBeDefined());
    const outer = submitted?.nodes[0];
    if (outer?.type !== "repeat" || outer.children[0]?.type !== "repeat") throw new Error("Expected nested repeats");
    expect(outer.children[0].children[0]).toMatchObject({
      target: { type: "rpe", min: 3, max: 4 },
      instructions: "Cotovelo alto",
    });
  });
});
