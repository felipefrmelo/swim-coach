import { expect, test } from "@playwright/test";

test("Garmin page is authenticated, mobile-first and never asks for a browser password", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Entrar no ambiente local" }).click();
  await page.getByRole("link", { name: "Garmin" }).click();

  await expect(page.getByRole("heading", { name: "Garmin" })).toBeVisible();
  await expect(page.getByText("A senha não é digitada nem armazenada neste navegador.")).toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await expect(page.getByText("A chave de criptografia Garmin ainda não foi configurada no servidor.")).toBeVisible();

  if (process.env.P02_EVIDENCE_SCREENSHOT) {
    await page.screenshot({ path: process.env.P02_EVIDENCE_SCREENSHOT });
  }
});
