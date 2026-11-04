import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { PlanDetail } from "../api/types";
import { PlanEditor } from "./plans";

const plan: PlanDetail = {
  plan_id: "plan", title: "Meu ciclo", status: "ACTIVE", lifecycle_state: "ACTIVE", current_revision: 9,
  local_date: "2026-11-04", protected_weeks: [1], sessions: [], history: [],
  definition: { title: "Meu ciclo", timezone: "America/Sao_Paulo", start_date: "2026-11-02", duration_weeks: 8, strategy_summary: "Evoluir com técnica", weeks: [
    { week_number: 1, focus: "Histórico", detail_level: "DETAILED", sessions: [{ session_intent_id: "locked", session_number: 1, purpose: "TECHNIQUE", scheduled_date: "2026-11-03" }] },
    { week_number: 2, focus: "Resistência", detail_level: "DETAILED", sessions: [{ session_intent_id: "future", session_number: 1, purpose: "ENDURANCE", scheduled_date: "2026-11-10", scheduled_start_time: "06:15", planned_duration_minutes: 45, target_distance_m: 1000, objective: "Continuidade", workout: { schema_version: "1.0", sport: "POOL_SWIMMING", title: "Crawl", purpose: "ENDURANCE", pool_length_m: 20, tags: [], nodes: [{ type: "step", step_role: "WORK", end_condition: { type: "distance", meters: 1000 }, stroke: { type: "freestyle" }, instructions: "Manter técnica", target: { type: "rpe", min: 3, max: 4 } }] } }] },
  ] },
};
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function show(value = plan) { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); render(<QueryClientProvider client={client}><PlanEditor plan={value} /></QueryClientProvider>); }

it("shows prescription and protects history while staging a complete revision before approval", async () => {
  const propose = vi.spyOn(api, "proposePlanEdit").mockResolvedValue({ proposal_id: "proposal", action_hash: "a".repeat(64), expected_revision: 9, expires_at: "2099-11-04T12:00:00Z", diff: { changed_weeks: [2] } });
  const apply = vi.spyOn(api, "applyPlanEdit").mockResolvedValue({ current_revision: 10 });
  show();
  expect(screen.getByText("Manter técnica")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Editar plano" }));
  expect(within(screen.getByRole("region", { name: "Semana 1" })).queryByRole("textbox")).not.toBeInTheDocument();
  const week = within(screen.getByRole("region", { name: "Semana 2" }));
  fireEvent.change(week.getByLabelText("Objetivo da sessão"), { target: { value: "Consolidar técnica" } });
  fireEvent.change(screen.getByLabelText("Motivo da alteração"), { target: { value: "Ajustar a próxima sessão" } });
  fireEvent.click(screen.getByRole("button", { name: "Revisar alterações" }));
  await screen.findByRole("button", { name: "Aprovar e salvar revisão" });
  expect(apply).not.toHaveBeenCalled();
  expect(propose.mock.calls[0][1].definition.weeks[0]).toEqual(plan.definition!.weeks[0]);
  expect(propose.mock.calls[0][1].definition.weeks[1].sessions[0].objective).toBe("Consolidar técnica");
  fireEvent.click(screen.getByRole("button", { name: "Aprovar e salvar revisão" }));
  await waitFor(() => expect(apply).toHaveBeenCalledWith("plan", expect.objectContaining({ action_hash: "a".repeat(64), expected_revision: 9 })));
});

it("discards edits and never stages or applies on cancellation", () => {
  const propose = vi.spyOn(api, "proposePlanEdit");
  show(); fireEvent.click(screen.getByRole("button", { name: "Editar plano" }));
  fireEvent.change(screen.getAllByLabelText("Foco da semana")[0], { target: { value: "Alterado" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancelar edição" }));
  expect(screen.getByText("Resistência")).toBeVisible(); expect(propose).not.toHaveBeenCalled();
});

it("keeps ended cycles readable without offering editing", () => {
  show({ ...plan, lifecycle_state: "ENDED_NEEDS_REVIEW" });
  expect(screen.getByText("Manter técnica")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Editar plano" })).not.toBeInTheDocument();
});

it("invalidates approval when the draft changes after preview", async () => {
  vi.spyOn(api, "proposePlanEdit").mockResolvedValue({ proposal_id: "proposal", action_hash: "a".repeat(64), expected_revision: 9, expires_at: "2099-11-04T12:00:00Z", diff: { changed_weeks: [2] } });
  show(); fireEvent.click(screen.getByRole("button", { name: "Editar plano" }));
  fireEvent.change(screen.getByLabelText("Objetivo da sessão"), { target: { value: "Novo objetivo" } });
  fireEvent.change(screen.getByLabelText("Motivo da alteração"), { target: { value: "Nova sessão" } });
  fireEvent.click(screen.getByRole("button", { name: "Revisar alterações" }));
  await screen.findByRole("button", { name: "Aprovar e salvar revisão" });
  fireEvent.change(screen.getByLabelText("Objetivo da sessão"), { target: { value: "Outro objetivo" } });
  expect(screen.queryByRole("button", { name: "Aprovar e salvar revisão" })).not.toBeInTheDocument();
});
