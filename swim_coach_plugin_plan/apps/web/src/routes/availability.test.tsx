import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { AvailabilityRule } from "../api/types";
import { AvailabilityPage } from "./pages";

const tuesday: AvailabilityRule = {
  id: "00000000-0000-0000-0000-000000000011",
  day_of_week: 1,
  start_local_time: "19:00:00",
  end_local_time: "20:00:00",
  max_duration_minutes: 60,
  pool_id: null,
  valid_from: null,
  valid_until: null,
  priority: 0,
  version: 1,
};

const thursday: AvailabilityRule = {
  ...tuesday,
  id: "00000000-0000-0000-0000-000000000012",
  day_of_week: 3,
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><AvailabilityPage /></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AvailabilityPage", () => {
  it("shows the correct weekday for every saved rule", async () => {
    vi.spyOn(api, "availability").mockResolvedValue([tuesday, thursday]);

    renderPage();

    expect(await screen.findByRole("heading", { name: "Terça-feira" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Quinta-feira" })).toBeVisible();
    expect(screen.getAllByLabelText("Dia da semana").map((field) => (field as HTMLSelectElement).value)).toEqual(["1", "3"]);
  });

  it("adds and edits availability before replacing the weekly schedule", async () => {
    vi.spyOn(api, "availability").mockResolvedValue([tuesday]);
    const replace = vi.spyOn(api, "replaceAvailability").mockResolvedValue([
      { ...tuesday, start_local_time: "18:30:00" },
      thursday,
    ]);
    renderPage();
    await screen.findByRole("heading", { name: "Terça-feira" });

    fireEvent.change(screen.getByLabelText("Início"), { target: { value: "18:30" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar horário" }));

    const dayFields = screen.getAllByLabelText("Dia da semana") as HTMLSelectElement[];
    expect(dayFields).toHaveLength(2);
    expect(dayFields[1].value).toBe("3");
    fireEvent.click(screen.getByRole("button", { name: "Salvar disponibilidade" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith([
      {
        day_of_week: 1,
        start_local_time: "18:30:00",
        end_local_time: "20:00:00",
        max_duration_minutes: 60,
        pool_id: null,
        valid_from: null,
        valid_until: null,
        priority: 0,
      },
      {
        day_of_week: 3,
        start_local_time: "19:00:00",
        end_local_time: "20:00:00",
        max_duration_minutes: 60,
        pool_id: null,
        valid_from: null,
        valid_until: null,
        priority: 0,
      },
    ]));
    expect(await screen.findByText("Disponibilidade atualizada.")).toBeVisible();
  });

  it("removes the final rule and saves an empty schedule", async () => {
    vi.spyOn(api, "availability").mockResolvedValue([tuesday]);
    const replace = vi.spyOn(api, "replaceAvailability").mockResolvedValue([]);
    renderPage();
    await screen.findByRole("heading", { name: "Terça-feira" });

    fireEvent.click(screen.getByRole("button", { name: "Remover Terça-feira" }));
    expect(screen.getByRole("heading", { name: "Sua agenda está vazia" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Salvar disponibilidade" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith([]));
  });

  it("prevents saving a window whose end is not after its start", async () => {
    vi.spyOn(api, "availability").mockResolvedValue([tuesday]);
    const replace = vi.spyOn(api, "replaceAvailability");
    renderPage();
    await screen.findByRole("heading", { name: "Terça-feira" });

    fireEvent.change(screen.getByLabelText("Fim"), { target: { value: "18:00" } });

    expect(screen.getByRole("alert")).toHaveTextContent("O horário final precisa ser depois do horário inicial.");
    expect(screen.getByRole("button", { name: "Salvar disponibilidade" })).toBeDisabled();
    expect(replace).not.toHaveBeenCalled();
  });
});
