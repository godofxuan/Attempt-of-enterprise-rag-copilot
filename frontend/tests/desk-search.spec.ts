import { test, expect } from "@playwright/test";
const headers = { "X-ESA-Request": "1" };

test("desk searches real tickets and keeps action previews bound to the matched ticket", async ({
  page,
  request,
}, info) => {
  const created = [];
  for (const kind of ["loan", "repair"]) {
    const facts =
      kind === "loan"
        ? {
            loan_start: "2026-12-10",
            loan_end: "2026-12-12",
            purpose: "服务台搜索演示",
          }
        : {
            asset_id: "employee-laptop-1",
            description: "搜索测试：屏幕无法点亮",
            impact: "medium",
          };
    const taskResponse = await request.post("/api/tasks", {
      headers,
      data: {
        request: {
          kind,
          execution_ceiling: "SUBMIT_AFTER_CONFIRMATION",
          confirmed: true,
          facts,
        },
      },
    });
    expect(taskResponse.ok()).toBeTruthy();
    const task = await taskResponse.json();
    const prepared = await request.post(
      `/api/product/tasks/${task.task_id}/prepare`,
      {
        headers,
        data: {
          expected_facts_revision: task.facts_revision,
          ...(kind === "loan" ? { asset_id: "loan-laptop-1" } : {}),
        },
      },
    );
    expect(prepared.ok()).toBeTruthy();
    const preview = await prepared.json();
    const submitted = await request.post(`/api/tasks/${task.task_id}/submit`, {
      headers,
      data: {
        proposal_id: preview.preview.proposal_id,
        content_digest: preview.preview.content_digest,
        expected_facts_revision: preview.revision,
        accepted: true,
      },
    });
    expect(submitted.ok()).toBeTruthy();
    created.push((await submitted.json()).receipt.ticket);
  }
  await page.goto("/#/desk");
  const cards = page.getByRole("article");
  const before = await cards.count();
  await expect(cards).toHaveCount(2);
  const input = page.getByRole("searchbox", { name: "搜索工单" });
  for (const term of [
    created[0].ticket_id,
    "  " + created[0].ticket_id.slice(0, 12).toUpperCase() + "  ",
    "loan-laptop-1",
    "服务台搜索演示",
    "待审批",
  ]) {
    await input.fill(term);
    await expect(cards).toHaveCount(1);
    await expect(
      page.getByRole("article", {
        name: "工单 " + created[0].ticket_id,
        exact: true,
      }),
    ).toBeVisible();
  }
  await page.getByRole("button", { name: "批准并预留", exact: true }).click();
  await page
    .getByLabel("处理说明", { exact: true })
    .fill("合成TEST：搜索定位后核对动作");
  const proposalResponse = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().endsWith("/api/service-desk/proposals"),
  );
  await page
    .getByRole("button", { name: "查看本次动作预览", exact: true })
    .click();
  const proposal = await (await proposalResponse).json();
  expect(proposal.content.ticket_id).toBe(created[0].ticket_id);
  await expect(
    page.getByRole("button", { name: "确认办理此动作", exact: true }),
  ).toBeVisible();
  // Search and opening a proposal must not approve the ticket.
  await page.keyboard.press("Escape");
  const actual = await (await request.get("/api/service-desk")).json();
  expect(
    actual.tickets.find((r: any) => r.ticket.ticket_id === created[0].ticket_id)
      .ticket.status,
  ).toBe("PENDING_APPROVAL");
  await input.fill("屏幕无法点亮");
  await expect(
    page.getByRole("article", {
      name: "工单 " + created[1].ticket_id,
      exact: true,
    }),
  ).toBeVisible();
  await expect(cards).toHaveCount(1);
  await input.fill("完全不存在的工单");
  await expect(cards).toHaveCount(0);
  await expect(
    page.getByText("没有匹配的工单，请缩短关键词或清空搜索。"),
  ).toBeVisible();
  await page.getByRole("button", { name: "清空搜索", exact: true }).click();
  await expect(cards).toHaveCount(2);
  await page.setViewportSize({ width: 390, height: 844 });
  await input.fill(created[0].ticket_id);
  await expect(cards).toHaveCount(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: info.outputPath("desk-search-mobile.png"),
    fullPage: true,
  });
});
