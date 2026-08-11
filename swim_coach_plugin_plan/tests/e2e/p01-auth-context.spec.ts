import { expect, test } from "@playwright/test";

test("authenticated user manages isolated initial context", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Entrar no ambiente local" }).click();
  await expect(page.getByRole("heading", { name: "Seu ponto de partida" })).toBeVisible();

  await page.getByRole("link", { name: "Perfil" }).click();
  await page.getByLabel("Como quer ser chamado").fill("Nadador local");
  await page.getByLabel("Sessões por semana").fill("4");
  await page.getByRole("button", { name: "Salvar perfil" }).click();
  await expect(page.getByText("Perfil atualizado com auditoria.")).toBeVisible();

  await page.getByRole("link", { name: "Piscinas" }).click();
  if ((await page.getByText("Piscina E2E").count()) === 0) {
    await page.getByLabel("Nome").fill("Piscina E2E");
    await page.getByLabel("Comprimento em metros").fill("25");
    await page.getByRole("button", { name: "Adicionar piscina" }).click();
    await expect(page.getByText("Piscina E2E")).toBeVisible();
  }

  await page.getByRole("link", { name: "Agenda" }).click();
  const addAvailability = page.getByRole("button", { name: "Adicionar terça, 19h–20h" });
  const availabilityWindow = page.getByText("19:00–20:00");
  await expect(addAvailability.or(availabilityWindow)).toBeVisible();
  if (await addAvailability.isVisible()) {
    await addAvailability.click();
  }
  await expect(availabilityWindow).toBeVisible();

  await page.getByRole("link", { name: "Meta" }).click();
  await page.getByLabel("Distância-alvo (m)").fill("2000");
  await page.getByLabel("Tempo-alvo (min)").fill("45");
  await page.getByRole("button", { name: "Salvar meta" }).click();
  await expect(page.getByText("Meta recalculada e salva.")).toBeVisible();

  await page.getByRole("link", { name: "Início" }).click();
  await expect(page.getByText("Meta de 2.000 m em 45 min")).toBeVisible();
  if (process.env.P01_EVIDENCE_SCREENSHOT) {
    await page.screenshot({ path: process.env.P01_EVIDENCE_SCREENSHOT, fullPage: true });
  }
});
