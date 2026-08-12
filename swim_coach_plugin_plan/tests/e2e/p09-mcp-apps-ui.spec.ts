import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const templatePath = resolve(
  process.cwd(),
  "../../backend/src/swim_coach/interfaces/mcp/assets/swim-coach-card-v1.html",
);
const template = readFileSync(templatePath, "utf8");

async function mountBridge(page: Page) {
  await page.setContent(`
    <!doctype html>
    <html><body style="margin:0">
      <iframe title="Swim Coach card" style="border:0;width:100%;height:800px"></iframe>
      <script>
        window.addEventListener("message", (event) => {
          const message = event.data;
          if (!message || message.jsonrpc !== "2.0" || message.method !== "tools/call") return;
          const calls = JSON.parse(document.body.dataset.calls || "[]");
          calls.push(message.params);
          document.body.dataset.calls = JSON.stringify(calls);
          event.source.postMessage({
            jsonrpc: "2.0",
            id: message.id,
            result: {
              structuredContent: {
                schema_version: "1.0",
                request_id: "bridge-response",
                status: "OK",
                data: { status: "APPROVED" },
                warnings: [],
                next_actions: [],
                human_summary: "Ação aprovada no servidor; execução ainda não iniciada.",
              },
            },
          }, "*");
        });
      </script>
    </body></html>
  `);
  await page.locator("iframe").evaluate((node, html) => {
    (node as HTMLIFrameElement).srcdoc = html;
  }, template);
  await expect(page.frameLocator("iframe").getByText("Carregando cartão do Swim Coach…")).toBeVisible();
}

async function deliver(page: Page, structuredContent: object) {
  await page.evaluate((payload) => {
    const frame = document.querySelector("iframe") as HTMLIFrameElement;
    frame.contentWindow?.postMessage(
      {
        jsonrpc: "2.0",
        method: "ui/notifications/tool-result",
        params: { structuredContent: payload },
      },
      "*",
    );
  }, structuredContent);
}

test("portable workout card is keyboard accessible and stays inside a mobile viewport", async ({ page }) => {
  await mountBridge(page);
  await deliver(page, {
    status: "OK",
    data: {
      card: {
        kind: "workout",
        title: "Técnica 1.600 m",
        subtitle: "2026-08-14",
        status: "approved",
        hash: `sha256:${"a".repeat(64)}`,
        metrics: [
          { label: "Distância", value: "1600 m" },
          { label: "Duração estimada", value: "42:00" },
          { label: "Piscina", value: "20 m" },
        ],
        items: [{ title: "Aquecimento", detail: "400 m", status: "easy" }],
        links: [{ label: "Abrir treino", href: "https://coach.example.test/workouts" }],
        warnings: [],
      },
    },
    human_summary: "Treino de 1.600 m.",
  });

  const card = page.frameLocator("iframe");
  await expect(card.getByRole("heading", { name: "Técnica 1.600 m" })).toBeVisible();
  await expect(card.getByText("1600 m")).toBeVisible();
  await expect(card.getByText("Aquecimento")).toBeVisible();
  await expect(card.getByRole("link", { name: "Abrir treino" })).toHaveAttribute(
    "href",
    "https://coach.example.test/workouts",
  );
  await card.getByRole("link", { name: "Abrir treino" }).focus();
  await expect(card.getByRole("link", { name: "Abrir treino" })).toBeFocused();
  const scrollWidth = await card.locator("html").evaluate((node) => node.scrollWidth);
  const clientWidth = await card.locator("html").evaluate((node) => node.clientWidth);
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
  if (process.env.P09_EVIDENCE_SCREENSHOT) {
    await page.screenshot({ path: process.env.P09_EVIDENCE_SCREENSHOT, fullPage: true });
  }
});

test("proposal card submits one exact-hash decision and never executes on double click", async ({ page }) => {
  await mountBridge(page);
  const proposalId = "00000000-0000-0000-0000-000000000909";
  const actionHash = "b".repeat(64);
  await deliver(page, {
    status: "OK",
    data: {
      card: {
        kind: "proposal",
        title: "Confirmar ação",
        subtitle: "GARMIN_PUBLISH",
        status: "READY_FOR_REVIEW",
        hash: actionHash,
        expired: false,
        metrics: [{ label: "Distância", value: "1600 m" }],
        items: [{ title: "Calendário", detail: "2026-08-14" }],
        warnings: [],
        decision: {
          tool: "approve_action_proposal",
          proposal_id: proposalId,
          expected_action_hash: actionHash,
        },
      },
    },
    human_summary: "Revise o hash exato.",
  });

  const approve = page.frameLocator("iframe").getByRole("button", { name: "Aprovar ação exata" });
  await expect(approve).toBeVisible();
  await approve.evaluate((button) => {
    (button as HTMLButtonElement).click();
    (button as HTMLButtonElement).click();
  });
  await expect.poll(async () => page.locator("body").getAttribute("data-calls")).not.toBeNull();

  const calls = JSON.parse((await page.locator("body").getAttribute("data-calls")) ?? "[]");
  expect(calls).toHaveLength(1);
  expect(calls[0].name).toBe("approve_action_proposal");
  expect(calls[0].arguments).toMatchObject({
    proposal_id: proposalId,
    expected_action_hash: actionHash,
    decision: "APPROVE",
  });
  expect(calls.some((call: { name: string }) => call.name === "execute_approved_action")).toBe(false);
  await expect(
    page.frameLocator("iframe").getByText("Ação aprovada no servidor; execução ainda não iniciada."),
  ).toBeVisible();
});

test("expired proposal is announced and cannot be approved", async ({ page }) => {
  await mountBridge(page);
  await deliver(page, {
    status: "OK",
    data: {
      card: {
        kind: "proposal",
        title: "Confirmar ação",
        status: "READY_FOR_REVIEW",
        expired: true,
        hash: "c".repeat(64),
        metrics: [],
        items: [],
        warnings: [],
        decision: null,
      },
    },
    human_summary: "Proposta expirada.",
  });

  const card = page.frameLocator("iframe");
  await expect(card.getByRole("alert")).toContainText("expirou");
  await expect(card.getByRole("button", { name: "Aprovar ação exata" })).toHaveCount(0);
});
