import { test, expect } from "@playwright/test";
const headers = { "X-ESA-Request": "1" };

test("knowledge-only recovery works without business dates and consumes only the missing answer", async ({
  page,
  request,
}, info) => {
  const created = await request.post("/api/library", {
    headers,
    data: { name: "恢复外部替身" },
  });
  expect(created.ok()).toBeTruthy();
  const kb = await created.json();
  const task = await (
    await request.post("/api/tasks", {
      headers,
      data: {
        kb_id: kb.id,
        request: {
          kind: "loan",
          execution_ceiling: "PREVIEW_ONLY",
          confirmed: true,
        },
      },
    })
  ).json();
  await request.post("/__test/decisions/" + task.task_id, {
    data: [
      [
        [
          "update_parameters",
          {
            changes: {},
            turn_request: { preview: false, knowledge_quote: "借用期限" },
          },
        ],
      ],
      [["knowledge_answer", { question: "借用期限" }]],
      [["finish", {}]],
    ],
  });
  await page.goto("/#/assistant?c=" + task.conversation_id);
  await page
    .getByRole("textbox", { name: "给助理发消息" })
    .fill("先解释借用期限，日期尚未决定，不生成预览。");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "重试解释", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("先解释借用期限，日期尚未决定，不生成预览。", {
      exact: true,
    }),
  ).toBeVisible();
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(
      page.getByRole("button", { name: "重试解释", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await expect(
      page.getByRole("textbox", { name: "给助理发消息" }),
    ).toHaveCount(1);
  }
  await page.screenshot({
    path: info.outputPath("knowledge-recovery-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "重试解释", exact: true }).click();
  await expect(
    page.getByText("UI外部回答替身，非实时模型。", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "重试解释", exact: true }),
  ).toHaveCount(0);
  const actual = await (await request.get("/api/tasks/" + task.task_id)).json();
  expect(actual.facts).toEqual({});
  expect(actual.preview).toBeNull();
  expect(actual.receipt).toBeFalsy();
  expect(
    (await (await request.get("/__test/counters")).json())
      .knowledge_recovery_attempts,
  ).toBe(2);
});

test("old items are paged and searchable, and history remains reachable on a phone", async ({
  page,
  request,
}, info) => {
  let oldest = "";
  for (let i = 0; i < 55; i++) {
    const task = await (
      await request.post("/api/tasks", {
        headers,
        data: {
          request: {
            kind: "loan",
            execution_ceiling: "READ_ONLY",
            confirmed: true,
            facts: { purpose: "分页合成事项" + i },
          },
        },
      })
    ).json();
    if (!i) oldest = task.task_id;
  }
  await page.goto("/#/requests");
  await expect(
    page.getByRole("button", { name: "查看事项", exact: true }),
  ).toHaveCount(20);
  await page.getByRole("button", { name: "更多事项", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "查看事项", exact: true }),
  ).toHaveCount(40);
  await page.getByRole("button", { name: "更多事项", exact: true }).click();
  await expect(page.getByText("分页合成事项0", { exact: true })).toBeVisible();
  await page.getByRole("searchbox", { name: "搜索事项" }).fill(oldest);
  await expect(
    page.getByRole("button", { name: "查看事项", exact: true }),
  ).toHaveCount(1);
  await page.getByRole("button", { name: "查看事项", exact: true }).click();
  await expect(
    page.getByRole("dialog").getByText("分页合成事项0", { exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 390, height: 844 });
  const history = page.locator("details.recent");
  await history.locator("summary").click();
  if (!((await history.getAttribute("open")) !== null))
    await history.locator("summary").click();
  await expect(page.getByRole("searchbox", { name: "搜索会话" })).toBeVisible();
  await page.screenshot({
    path: info.outputPath("history-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});

test("preview expiry changes the visible action without a failed submit first", async ({
  page,
  request,
}, info) => {
  await page.clock.install();
  const task = await (
    await request.post("/api/tasks", {
      headers,
      data: {
        request: {
          kind: "loan",
          execution_ceiling: "SUBMIT_AFTER_CONFIRMATION",
          confirmed: true,
          facts: {
            loan_start: "2026-12-22",
            loan_end: "2026-12-23",
            purpose: "截止浏览器合成验证",
          },
        },
      },
    })
  ).json();
  const prepared = await (
    await request.post("/api/product/tasks/" + task.task_id + "/prepare", {
      headers,
      data: {
        asset_id: "loan-laptop-1",
        expected_facts_revision: task.facts_revision,
      },
    })
  ).json();
  try {
    await page.goto(
      `/#/assistant?c=${task.conversation_id}&task=${task.task_id}`,
    );
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("button", { name: "确认并提交当前预览" }),
    ).toBeVisible();
    await request.post("/__test/clock", { data: { offset: 601 } });
    await page.clock.fastForward(601_000);
    await expect(
      dialog.getByRole("heading", { name: "已过期的预览（仅供参考）" }),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "确认并提交当前预览" }),
    ).toHaveCount(0);
    await expect(
      dialog.getByRole("button", { name: "重新生成预览", exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: info.outputPath("expired-preview.png"),
      fullPage: true,
    });
    const rejected = await request.post(
      "/api/tasks/" + task.task_id + "/submit",
      {
        headers,
        data: {
          proposal_id: prepared.preview.proposal_id,
          content_digest: prepared.preview.content_digest,
          expected_facts_revision: prepared.revision,
          accepted: true,
        },
      },
    );
    expect(rejected.status()).toBe(409);
    expect((await rejected.json()).error.code).toBe("CONFIRMATION_EXPIRED");
    await dialog
      .getByRole("button", { name: "重新生成预览", exact: true })
      .click();
    await expect(
      dialog.getByRole("heading", { name: "当前完整预览", exact: true }),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "确认并提交当前预览" }),
    ).toBeVisible();
    const actual = await (
      await request.get("/api/tasks/" + task.task_id)
    ).json();
    expect(actual.preview.proposal_id).not.toBe(prepared.preview.proposal_id);
    expect(actual.receipt).toBeFalsy();
  } finally {
    await request.post("/__test/clock", { data: { offset: 0 } });
  }
});
