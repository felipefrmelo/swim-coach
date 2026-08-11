import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const me = {
  user: { id: "00000000-0000-0000-0000-000000000001", email: "swimmer@example.test", display_name: "Nadador", locale: "pt-BR", timezone: "America/Sao_Paulo", version: 1 },
  profile: { experience_level: "recreational", default_sessions_per_week: 3, preferred_distance_unit: "m", default_pool_id: "00000000-0000-0000-0000-000000000002", version: 1 },
};

function jsonResponse(value: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(value), { status, headers: { "Content-Type": status >= 400 ? "application/problem+json" : "application/json" } }));
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("shows an honest authenticated P01 dashboard", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/auth/config")) return jsonResponse({ oidc_enabled: false, dev_auth_enabled: true });
      if (path.endsWith("/me")) return jsonResponse(me);
      if (path.endsWith("/pools")) return jsonResponse([{ id: me.profile.default_pool_id, name: "Piscina principal", length_m: 20, is_default: true, location_label: null, active: true, version: 1 }]);
      if (path.endsWith("/goals")) return jsonResponse([{ id: "00000000-0000-0000-0000-000000000003", title: "Nadar 2.000 m em 45 min", status: "active", priority: 1, target_distance_m: 2000, target_duration_seconds: "2700", target_pace_seconds_per_100m: "135", target_date: null, version: 1 }]);
      return jsonResponse([]);
    }));

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Seu ponto de partida" })).toBeVisible();
    expect(screen.getByText("Piscina padrão de 20 m")).toBeVisible();
    expect(screen.getByText(/editor e o calendário de treinos entram no P04/i)).toBeVisible();
    expect(screen.queryByText(/chat/i)).not.toBeInTheDocument();
  });

  it("offers an explicit local login when no session exists", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (String(input).endsWith("/auth/config")) return jsonResponse({ oidc_enabled: false, dev_auth_enabled: true });
      return jsonResponse({ code: "AUTH_REQUIRED", detail: "Authentication is required.", correlation_id: "fixture" }, 401);
    }));

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Entre no Swim Coach" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Entrar no ambiente local" })).toBeVisible();
  });
});
