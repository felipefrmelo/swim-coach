import { expect, test } from "@playwright/test";

test("user saves and sends a workout to Garmin in one action", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Entrar no ambiente local" }).click();
  await page.getByRole("link", { name: "Treinos" }).click();
  await page.getByRole("link", { name: "Criar treino" }).click();
  const saveResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/v1/workouts/save") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Salvar e enviar ao Garmin" }).click();
  const response = await saveResponse;
  expect(response.ok()).toBeTruthy();
  const result = await response.json();
  expect(result.garmin.status).toBe("queued");
  await expect(page.getByRole("heading", { name: "Editar treino" })).toBeVisible();
  await expect(page.getByText(/Aguardando sua decisão|hash|aprovar publicação/i)).toHaveCount(0);
  if (process.env.P07_EVIDENCE_SCREENSHOT) {
    await page.screenshot({ path: process.env.P07_EVIDENCE_SCREENSHOT, fullPage: true });
  }
});
