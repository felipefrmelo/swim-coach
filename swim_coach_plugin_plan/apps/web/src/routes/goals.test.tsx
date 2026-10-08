import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { Goal } from "../api/types";
import { DashboardPage, GoalsPage } from "./pages";

const goal: Goal = {
  id: "00000000-0000-0000-0000-000000000003",
  title: "Nadar 2.000 m em 45 min",
  status: "active",
  priority: 1,
  target_distance_m: 1000,
  target_duration_seconds: "1800",
  target_pace_seconds_per_100m: "180",
  target_date: null,
  version: 1,
};

function renderPages() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  queryClient.setQueryData(["me"], {});
  queryClient.setQueryData(["pools"], []);
  queryClient.setQueryData(["availability"], []);
  return render(<QueryClientProvider client={queryClient}><DashboardPage /><GoalsPage /></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Dashboard goal", () => {
  it("uses the saved duration in both summaries and refreshes after editing the goal", async () => {
    let savedGoal = goal;
    vi.spyOn(api, "goals").mockImplementation(async () => [savedGoal]);
    vi.spyOn(api, "updateGoal").mockImplementation(async (updated) => {
      savedGoal = { ...updated, version: 2 };
      return savedGoal;
    });
    renderPages();

    expect(await screen.findByText("Meta em 30 minutos")).toBeVisible();
    expect(screen.getByText("Meta de 1.000 m em 30 min")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Tempo-alvo (min)"), { target: { value: "25" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar meta" }));

    expect(await screen.findByText("Meta em 25 minutos")).toBeVisible();
    expect(screen.getByText("Meta de 1.000 m em 25 min")).toBeVisible();
    expect(screen.queryByText(/Meta.*45 min/)).not.toBeInTheDocument();
  });

  it("does not invent a duration when there is no active goal", async () => {
    vi.spyOn(api, "goals").mockResolvedValue([{ ...goal, status: "completed" }]);
    renderPages();

    expect(await screen.findByText("Nenhuma meta ativa")).toBeVisible();
    expect(screen.queryByText(/Meta de .* min/)).not.toBeInTheDocument();
  });
});
