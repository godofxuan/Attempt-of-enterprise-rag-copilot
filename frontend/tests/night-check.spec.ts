import { test, expect } from "@playwright/test";
const headers = { "X-ESA-Request": "1" };

for (const operation of ["retry", "binding"])
  test(`delayed ${operation} failure stays with the originating conversation`, async ({
    page,
    request,
  }) => {
    const kb = await (
      await request.post("/api/library", {
        headers,
        data: { name: "夜间归属检查" },
      })
    ).json();
    const a = await (
      await request.post("/api/conversations", {
        headers,
        data: { title: "操作中的A" },
      })
    ).json();
    const b = await (
      await request.post("/api/conversations", {
        headers,
        data: { title: "保留草稿的B", kb_id: kb.id },
      })
    ).json();
    const mid = "missing-scope-" + operation;
    if (operation === "retry") {
      const started = await (
        await request.post(`/api/conversations/${a.id}/turns`, {
          headers,
          data: { message_id: mid, text: "合成知识问题" },
        })
      ).json();
      await expect
        .poll(
          async () =>
            (await (await request.get("/api/runs/" + started.id)).json())
              .status,
        )
        .toBe("failed");
      expect(
        (
          await request.patch("/api/conversations/" + a.id, {
            headers,
            data: { kb_id: kb.id },
          })
        ).ok(),
      ).toBeTruthy();
    }
    await page.goto("/#/assistant?c=" + b.id);
    await page.getByRole("textbox", { name: "给助理发消息" }).fill("B的新草稿");
    await page.locator(`a[href="#/assistant?c=${a.id}"]`).click();
    let release!: () => void, reached!: () => void;
    const held = new Promise<void>((r) => (release = r)),
      pending = new Promise<void>((r) => (reached = r));
    const endpoint =
      operation === "retry"
        ? `/api/product/conversations/${a.id}/turns/${mid}/retry`
        : `/api/conversations/${a.id}`;
    const method = operation === "retry" ? "POST" : "PATCH";
    await page.route("**" + endpoint, async (route) => {
      if (route.request().method() !== method) return route.continue();
      await route.fetch();
      reached();
      await held;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            code: "SIMULATED_OWNER_FAILURE",
            message: "只属于A的迟到故障",
          },
        }),
      });
    });
    try {
      if (operation === "retry")
        await page
          .getByRole("button", { name: "重试这条消息", exact: true })
          .click();
      else
        await page
          .getByRole("combobox", { name: "当前资料库" })
          .selectOption(kb.id);
      await pending;
      await page.locator(`a[href="#/assistant?c=${b.id}"]`).click();
      await expect(
        page.getByRole("combobox", { name: "当前资料库" }),
      ).toBeEnabled();
      const delivered = page.waitForResponse(
        (r) => r.request().method() === method && r.url().endsWith(endpoint),
      );
      release();
      await delivered;
      await expect(page.getByRole("alert")).toHaveCount(0);
      await expect(
        page.getByRole("textbox", { name: "给助理发消息" }),
      ).toHaveValue("B的新草稿");
      await page.locator(`a[href="#/assistant?c=${a.id}"]`).click();
      await expect(page.getByRole("alert")).toBeVisible();
      await page
        .getByRole("alert")
        .getByText("查看原因", { exact: true })
        .click();
      await expect(page.getByText(/只属于A的迟到故障/)).toBeVisible();
    } finally {
      release();
    }
  });

test("successful receipt readback replaces the submitting message", async ({
  page,
  request,
}) => {
  const task = await (
    await request.post("/api/tasks", {
      headers,
      data: {
        request: {
          kind: "loan",
          execution_ceiling: "SUBMIT_AFTER_CONFIRMATION",
          confirmed: true,
          facts: {
            loan_start: "2026-12-25",
            loan_end: "2026-12-26",
            purpose: "提交后提示核验",
          },
        },
      },
    })
  ).json();
  const prepared = await request.post(
    `/api/product/tasks/${task.task_id}/prepare`,
    {
      headers,
      data: {
        asset_id: "loan-laptop-1",
        expected_facts_revision: task.facts_revision,
      },
    },
  );
  expect(prepared.ok()).toBeTruthy();
  let ticketId: string | undefined;
  let releaseReadback!: () => void, readbackReached!: () => void;
  const heldReadback = new Promise<void>(
    (resolve) => (releaseReadback = resolve),
  );
  const waitingForReadback = new Promise<void>(
    (resolve) => (readbackReached = resolve),
  );
  try {
    await page.goto(
      `/#/assistant?c=${task.conversation_id}&task=${task.task_id}`,
    );
    const dialog = page.getByRole("dialog");
    await dialog
      .getByRole("button", { name: "确认并提交当前预览", exact: true })
      .waitFor();
    await page.route(`**/api/product/tasks/${task.task_id}`, async (route) => {
      const actual = await route.fetch();
      if ((await actual.json()).current_ticket) {
        readbackReached();
        await heldReadback;
      }
      await route.fulfill({ response: actual });
    });
    const response = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().endsWith(`/api/tasks/${task.task_id}/submit`),
    );
    await dialog
      .getByRole("button", { name: "确认并提交当前预览", exact: true })
      .click();
    const receipt = (await (await response).json()).receipt;
    ticketId = receipt.ticket_id;
    await waitingForReadback;
    await expect(dialog.locator(".detail-summary")).toContainText("正在读回");
    await expect(
      dialog.getByRole("heading", { name: "当前办理结果", exact: true }),
    ).toHaveCount(0);
    releaseReadback();
    await expect(
      dialog.getByRole("heading", { name: "当前办理结果", exact: true }),
    ).toBeVisible();
    await expect(dialog.locator(".detail-summary")).not.toContainText(
      "正在读回",
    );
    await expect(dialog).toContainText("待审批");
    const view = await (
      await request.get(`/api/product/tasks/${task.task_id}`)
    ).json();
    expect(view.current_ticket.ticket_id).toBe(ticketId);
    expect(view.can_submit).toBe(false);
  } finally {
    releaseReadback();
    if (ticketId) {
      const row = (
        await (await request.get("/api/service-desk")).json()
      ).tickets.find((x: any) => x.ticket.ticket_id === ticketId);
      const proposal = await (
        await request.post("/api/service-desk/proposals", {
          headers,
          data: {
            kind: "loan",
            ticket_id: ticketId,
            action: "withdraw",
            expected_version: row.ticket.version,
            note: "合成测试结束，撤回本例工单",
          },
        })
      ).json();
      expect(
        (
          await request.post("/api/service-desk/commit", {
            headers,
            data: {
              proposal_id: proposal.proposal_id,
              content_digest: proposal.content_digest,
              accepted: true,
            },
          })
        ).ok(),
      ).toBeTruthy();
    }
  }
});
