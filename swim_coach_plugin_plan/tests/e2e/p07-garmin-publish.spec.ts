import { expect, test } from "@playwright/test";

test("user saves and sends a workout to Garmin in one action", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Entrar no ambiente local" }).click();
  await page.getByRole("link", { name: "Treinos" }).click();
  await page.getByRole("link", { name: "Criar treino" }).click();
  await page.getByLabel("Tipo de meta").first().selectOption("rpe");
  await page.getByLabel("RPE mínimo").first().fill("5");
  await page.getByLabel("RPE máximo").first().fill("6");
  await page.getByLabel("Notas").first().fill("Respiração bilateral");
  const saveResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/v1/workouts/save") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Salvar e enviar ao Garmin" }).click();
  const response = await saveResponse;
  expect(response.ok()).toBeTruthy();
  const request = response.request().postDataJSON();
  expect(request.definition.nodes[0].target).toEqual({ type: "rpe", min: 5, max: 6 });
  expect(request.definition.nodes[0].instructions).toBe("Respiração bilateral");
  const result = await response.json();
  expect(result.garmin.status).toBe("queued");
  await expect(page.getByRole("heading", { name: "Editar treino" })).toBeVisible();
  await expect(page.getByLabel("Tipo de meta").first()).toHaveValue("rpe");
  await expect(page.getByLabel("Notas").first()).toHaveValue("Respiração bilateral");
  await page.reload();
  await expect(page.getByLabel("Tipo de meta").first()).toHaveValue("rpe");
  await expect(page.getByLabel("RPE mínimo").first()).toHaveValue("5");
  await expect(page.getByLabel("RPE máximo").first()).toHaveValue("6");
  await expect(page.getByLabel("Notas").first()).toHaveValue("Respiração bilateral");
  await expect(page.getByText(/Aguardando sua decisão|hash|aprovar publicação/i)).toHaveCount(0);
  if (process.env.P07_EVIDENCE_SCREENSHOT) {
    await page.screenshot({ path: process.env.P07_EVIDENCE_SCREENSHOT, fullPage: true });
  }
});
