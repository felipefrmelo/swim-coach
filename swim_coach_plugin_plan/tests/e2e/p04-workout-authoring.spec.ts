import { expect, test } from "@playwright/test";

test("user creates, approves and schedules a canonical 1,600 m workout", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Entrar no ambiente local" }).click();
  await page.getByRole("link", { name: "Treinos" }).click();
  await page.getByRole("link", { name: "Criar treino" }).click();

  await expect(page.getByText("1.600 m", { exact: true })).toBeVisible();
  await expect(page.getByText("Todas as distâncias terminam na parede")).toBeVisible();
  await page.getByRole("button", { name: "Criar rascunho" }).click();

  await expect(page.getByRole("heading", { name: "Histórico imutável" })).toBeVisible();
  await expect(page.getByText("Revisão 1 · 1.600 m")).toBeVisible();
  await page.getByRole("button", { name: "Aprovar esta revisão localmente" }).click();
  await expect(page.getByRole("button", { name: "Agendar treino" })).toBeEnabled();
  await page.getByRole("button", { name: "Agendar treino" }).click();
  await expect(page.getByRole("button", { name: "Reagendar treino" })).toBeVisible();

  await page.getByLabel("Nome do treino").fill("Endurance revisado — 1.600 m");
  await page.getByLabel("Motivo da nova revisão").fill("Título mais claro");
  await page.getByRole("button", { name: "Salvar nova revisão" }).click();
  await expect(page.getByText("Revisão 2 · 1.600 m")).toBeVisible();

  if (process.env.P04_EVIDENCE_SCREENSHOT) {
    await page.screenshot({ path: process.env.P04_EVIDENCE_SCREENSHOT, fullPage: true });
  }
});

test("editor flags a 50 m step in a 20 m pool", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Entrar no ambiente local" }).click();
  await page.getByRole("link", { name: "Treinos" }).click();
  await page.getByRole("link", { name: "Criar treino" }).click();
  const distanceInputs = page.getByLabel("Distância (m)");
  await distanceInputs.first().fill("50");
  await expect(page.getByText("50 m não termina na parede de 20 m.")).toBeVisible();
});
