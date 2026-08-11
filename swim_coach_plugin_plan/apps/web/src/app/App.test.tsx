import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("labels P00 integrations as disabled", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Swim Coach" })).toBeVisible();
    expect(screen.getByText(/Nenhum dado Garmin está conectado/)).toBeVisible();
    expect(screen.getByText(/ChatGPT ou Codex/)).toBeVisible();
  });
});
