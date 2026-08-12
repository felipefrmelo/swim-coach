import { expect, test } from "@playwright/test";

test("user reviews exact impact and publishes a workout once through the fake provider", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Entrar no ambiente local" }).click();
  await page.getByRole("link", { name: "Treinos" }).click();
  await page.getByRole("link", { name: "Criar treino" }).click();
  await page.getByRole("button", { name: "Criar rascunho" }).click();
  await page.getByRole("button", { name: "Aprovar esta revisão localmente" }).click();
  await page.getByRole("button", { name: "Agendar treino" }).click();

  await expect(page.getByRole("heading", { name: "Revisar publicação Garmin" })).toBeVisible();
  await page.getByRole("button", { name: "Revisar antes de publicar" }).click();
  await expect(page.getByRole("heading", { name: "Aguardando sua decisão" })).toBeVisible();
  await expect(page.getByText("Treino local aprovado")).toBeVisible();
  await expect(page.getByText("Biblioteca + calendário Garmin")).toBeVisible();
  await expect(page.getByText("Relógio simulado · Garmin fake local")).toBeVisible();
  const approval = page.getByRole("button", { name: "Aprovar publicação de 1.600 m" });
  await expect(approval).toBeEnabled();
  await approval.click();

  await expect(page.getByRole("heading", { name: "Publicado e agendado" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Concluído")).toBeVisible();
  await expect(approval).toHaveCount(0);
  if (process.env.P07_EVIDENCE_SCREENSHOT) {
    await page.screenshot({ path: process.env.P07_EVIDENCE_SCREENSHOT, fullPage: true });
  }
});
