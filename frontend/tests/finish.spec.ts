import { test, expect } from "@playwright/test";
const headers = { "X-ESA-Request": "1" };

test("saved facts advance revision before prepare needs a device; next edit uses saved baseline", async ({
  page,
  request,
}, info) => {
  const task = await (
    await request.post("/api/tasks", {
      headers,
      data: {
        request: {
          kind: "loan",
          execution_ceiling: "PREVIEW_ONLY",
          confirmed: true,
          facts: {
            loan_start: "2026-12-07",
            loan_end: "2026-12-09",
            purpose: "原始用途",
          },
        },
      },
    })
  ).json();
  const payloads: unknown[] = [];
  page.on("request", (r) => {
    if (r.method() === "PATCH" && r.url().endsWith("/facts"))
      payloads.push(r.postDataJSON());
  });
  await page.goto(
    `/#/assistant?c=${task.conversation_id}&task=${task.task_id}`,
  );
  const editor = page.getByRole("dialog");
  await editor.getByLabel(/用途/).fill("已经保存的新用途");
  const first = page.waitForResponse(
    (r) => r.request().method() === "PATCH" && r.url().endsWith("/facts"),
  );
  await editor.getByRole("button", { name: /^保存(参数|并生成预览)$/ }).click();
  expect((await first).status()).toBe(200);
  await expect(
    editor.getByText("已保存参数 · 版本 " + (task.facts_revision + 1), {
      exact: true,
    }),
  ).toBeVisible();
  await editor.getByLabel(/用途/).fill("第二次明确修改的用途");
  const second = page.waitForResponse(
    (r) => r.request().method() === "PATCH" && r.url().endsWith("/facts"),
  );
  await editor.getByRole("button", { name: /^保存(参数|并生成预览)$/ }).click();
  const response = await second;
  await info.attach("facts-requests", {
    body: JSON.stringify({ payloads, response: await response.json() }),
    contentType: "application/json",
  });
  expect(response.status()).toBe(200);
  await expect(editor.getByText(/参数已保存.*选择设备/)).toBeVisible();
  await expect(
    editor
      .locator("details")
      .filter({ has: page.getByText("可选设备与日期", { exact: true }) }),
  ).toHaveAttribute("open", "");
  const actual = await (await request.get("/api/tasks/" + task.task_id)).json();
  expect(actual.facts.purpose).toBe("第二次明确修改的用途");
  expect(actual.facts_revision).toBe(task.facts_revision + 2);
  expect(
    (payloads[1] as { expected_facts_revision: number })
      .expected_facts_revision,
  ).toBe(task.facts_revision + 1);
  await editor
    .getByRole("radio", { name: "选择设备 loan-laptop-1", exact: true })
    .check();
  await editor
    .getByRole("button", { name: "选择并生成预览", exact: true })
    .click();
  await expect(
    editor.getByRole("heading", { name: "当前完整预览", exact: true }),
  ).toBeVisible();
  await expect(
    editor.getByRole("button", { name: "确认并提交当前预览" }),
  ).toHaveCount(0);
});

test("revision conflict retains the unsaved draft and exposes current server facts", async ({
  page,
  request,
}) => {
  const task = await (
    await request.post("/api/tasks", {
      headers,
      data: {
        request: {
          kind: "loan",
          execution_ceiling: "PREVIEW_ONLY",
          confirmed: true,
          facts: {
            loan_start: "2026-12-11",
            loan_end: "2026-12-13",
            purpose: "原用途",
          },
        },
      },
    })
  ).json();
  await page.goto(
    `/#/assistant?c=${task.conversation_id}&task=${task.task_id}`,
  );
  const editor = page.getByRole("dialog");
  await editor.getByLabel(/用途/).fill("这页未保存草稿");
  const other = await request.patch(`/api/tasks/${task.task_id}/facts`, {
    headers,
    data: {
      changes: { purpose: "另一页已保存的用途" },
      expected_facts_revision: task.facts_revision,
    },
  });
  expect(other.status()).toBe(200);
  const conflict = page.waitForResponse(
    (r) => r.request().method() === "PATCH" && r.url().endsWith("/facts"),
  );
  await editor.getByRole("button", { name: /^保存(参数|并生成预览)$/ }).click();
  expect((await conflict).status()).toBe(409);
  await expect(editor.getByLabel(/用途/)).toHaveValue("这页未保存草稿");
  await expect(
    editor.getByText(
      "服务器参数已更新，你的草稿保留。请比较最新值后重新编辑。",
    ),
  ).toBeVisible();
  expect(
    (await (await request.get("/api/tasks/" + task.task_id)).json()).facts
      .purpose,
  ).toBe("另一页已保存的用途");
  await editor.getByRole("button", { name: "载入服务器最新值" }).click();
  await expect(editor.getByLabel(/用途/)).toHaveValue("另一页已保存的用途");
});

test("normal model clarification is waiting input, focuses required fields and continues the same repair", async ({
  page,
  request,
}) => {
  const task = await (
    await request.post("/api/tasks", {
      headers,
      data: {
        request: {
          kind: "repair",
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
            changes: { description: "笔记本无法开机" },
            turn_request: { preview: true, knowledge_quote: "" },
          },
        ],
      ],
      [
        [
          "ask_user",
          {
            fields: ["asset_id", "impact"],
            reason: "missing",
            question: "请补充设备编号和影响程度。",
          },
        ],
      ],
    ],
  });
  const run = await (
    await request.post(`/api/conversations/${task.conversation_id}/turns`, {
      headers,
      data: {
        message_id: "finish-repair-input",
        text: "笔记本无法开机，请准备报修预览。",
      },
    })
  ).json();
  await expect
    .poll(
      async () =>
        (await (await request.get("/api/runs/" + run.id)).json()).status,
    )
    .toBe("succeeded");
  await page.goto("/#/assistant?c=" + task.conversation_id);
  await expect(
    page.getByText("等待补充必要信息", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /重试/ })).toHaveCount(0);
  const opener = page.getByRole("button", {
    name: "补充事项信息",
    exact: true,
  });
  await opener.click();
  const editor = page.getByRole("dialog");
  await expect(editor.locator('[data-field-name="asset_id"]')).toBeFocused();
  await editor
    .locator('[data-field-name="asset_id"]')
    .fill("employee-laptop-1");
  await editor.locator('[data-field-name="impact"]').selectOption("high");
  await editor.getByRole("button", { name: "保存参数", exact: true }).click();
  await expect(
    editor.getByRole("heading", { name: "当前完整预览" }),
  ).toBeVisible();
  const after = await (await request.get("/api/tasks/" + task.task_id)).json();
  expect(after.task_id).toBe(task.task_id);
  expect(after.receipt).toBeNull();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("six live page states, keyboard focus, long text and narrow layout use one readable presentation", async ({
  page,
  request,
}, info) => {
  const kb = (
    await (
      await request.post("/api/library", {
        headers,
        data: { name: "收尾视觉验证（外部模型替身）" },
      })
    ).json()
  ).id;
  const c = await (
    await request.post("/api/conversations", {
      headers,
      data: { kb_id: kb, title: "来源、状态和下一步" },
    })
  ).json();
  await page.goto("/#/assistant?c=" + c.id);
  await page
    .getByLabel("给助理发消息", { exact: true })
    .fill(
      "长说明".repeat(90) + '<img src=x onerror="window.esaInjected=true">',
    );
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(
    page.getByText("UI外部回答替身，非实时模型。", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(() =>
      Boolean((window as unknown as { esaInjected?: boolean }).esaInjected),
    ),
  ).toBe(false);
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  const assertLayout = async (width: number) => {
    await page.setViewportSize({ width, height: 950 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    const message = await page.locator(".message").last().boundingBox();
    const input = await page.locator(".composer").boundingBox();
    expect(
      message && input && message.y + message.height <= input.y,
    ).toBeTruthy();
  };
  for (const width of [1440, 1024, 390]) await assertLayout(width);
  await page.screenshot({
    path: info.outputPath("mobile-conversation.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: info.outputPath("desktop-conversation.png"),
    fullPage: true,
  });
  const task = await (
    await request.post("/api/tasks", {
      headers,
      data: {
        conversation_id: c.id,
        kb_id: kb,
        request: {
          kind: "loan",
          execution_ceiling: "SUBMIT_AFTER_CONFIRMATION",
          confirmed: true,
          facts: {
            loan_start: "2026-12-16",
            loan_end: "2026-12-18",
            purpose: "统一视觉的合成TEST任务",
          },
        },
      },
    })
  ).json();
  await page.reload();
  const opener = page.getByRole("button", { name: /查看参数与下一步/ });
  await opener.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator("details.resource-options")).toHaveAttribute(
    "open",
    "",
  );
  await page.screenshot({
    path: info.outputPath("device-choice.png"),
    fullPage: true,
  });
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press("Tab");
    expect(
      await dialog.evaluate((el) => el.contains(document.activeElement)),
    ).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(opener).toBeFocused();
  await opener.click();
  await dialog
    .getByRole("radio", { name: "选择设备 loan-laptop-2", exact: true })
    .check();
  await dialog
    .getByRole("button", { name: "选择并生成预览", exact: true })
    .click();
  await expect(
    dialog.getByRole("heading", { name: "当前完整预览" }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("preview.png"),
    fullPage: true,
  });
  await dialog.getByRole("button", { name: "确认并提交当前预览" }).dblclick();
  await expect(
    dialog.getByRole("heading", { name: "当前办理结果" }),
  ).toBeVisible();
  const submitted = await (
    await request.get("/api/tasks/" + task.task_id)
  ).json();
  expect(submitted.receipt.ticket.status).toBe("PENDING_APPROVAL");
  const again = await request.post("/api/tasks/" + task.task_id + "/submit", {
    headers,
    data: {
      proposal_id: submitted.preview.proposal_id,
      content_digest: submitted.preview.content_digest,
      expected_facts_revision: submitted.facts_revision,
      accepted: true,
    },
  });
  expect((await again.json()).receipt.command_id).toBe(
    submitted.receipt.command_id,
  );
  await page.screenshot({
    path: info.outputPath("receipt.png"),
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await page.getByRole("link", { name: "▥ 资料库", exact: true }).click();
  await page.getByLabel("查看资料库").selectOption(kb);
  await page.getByLabel("上传文档", { exact: true }).setInputFiles([
    {
      name: "非常长的制度文件名称".repeat(6) + ".md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# 合成说明\n真实文件解析，外部模型在本场景为替身。"),
    },
    {
      name: "不支持的文件.exe",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("not executable: synthetic upload error case"),
    },
  ]);
  await expect(
    page.getByRole("heading", { name: "本次导入结果" }),
  ).toBeVisible();
  await expect(
    page.getByText("不支持的文件.exe", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("查看此文件失败原因", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("library.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "当前工作区与版本" }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("settings.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "演示服务台", exact: true }).click();
  await expect(
    page.getByText("仅处理本地合成 TEST 工单，不连接企业审批系统。"),
  ).toBeVisible();
  const processTicket = async (ticketId: string, actions: string[]) => {
    for (const action of actions) {
      const rows = await (await request.get("/api/service-desk")).json();
      const row = rows.tickets.find(
        (r: any) => r.ticket.ticket_id === ticketId,
      );
      const operation = row.actions.find((a: any) => a.name === action);
      expect(operation).toBeTruthy();
      await page
        .getByRole("article", { name: "工单 " + ticketId, exact: true })
        .getByRole("button", { name: operation.label, exact: true })
        .click();
      await page
        .getByLabel("处理说明", { exact: true })
        .fill("明确的合成TEST操作：" + operation.label);
      if (action === "extend")
        await page
          .getByLabel("新的结束日期", { exact: true })
          .fill("2026-12-19");
      await page
        .getByRole("button", { name: "查看本次动作预览", exact: true })
        .click();
      await page
        .getByRole("button", { name: "确认办理此动作", exact: true })
        .click();
      await expect(page.getByRole("dialog")).toHaveCount(0);
    }
  };
  // Complete real business transitions, retain history, and release the sole
  // user's open loan. Do not reset SQLite between the following regressions.
  await processTicket(submitted.receipt.ticket_id, [
    "approve",
    "checkout",
    "extend",
    "return",
  ]);
  const repair = await (
    await request.post("/api/tasks", {
      headers,
      data: {
        request: {
          kind: "repair",
          execution_ceiling: "SUBMIT_AFTER_CONFIRMATION",
          confirmed: true,
          facts: {
            asset_id: "employee-laptop-1",
            description: "合成测试屏幕故障",
            impact: "high",
          },
        },
      },
    })
  ).json();
  const repairPreview = await (
    await request.post("/api/product/tasks/" + repair.task_id + "/prepare", {
      headers,
      data: { expected_facts_revision: repair.facts_revision },
    })
  ).json();
  const repairReceipt = await (
    await request.post("/api/tasks/" + repair.task_id + "/submit", {
      headers,
      data: {
        proposal_id: repairPreview.preview.proposal_id,
        content_digest: repairPreview.preview.content_digest,
        expected_facts_revision: repairPreview.revision,
        accepted: true,
      },
    })
  ).json();
  await page.reload();
  await processTicket(repairReceipt.receipt.ticket_id, [
    "start",
    "resolve",
    "close",
    "reopen",
    "start",
    "resolve",
    "close",
  ]);
  const final = await (await request.get("/api/service-desk")).json();
  expect(
    final.tickets.find(
      (r: any) => r.ticket.ticket_id === submitted.receipt.ticket_id,
    ).ticket.status,
  ).toBe("RETURNED");
  expect(
    final.tickets.find(
      (r: any) => r.ticket.ticket_id === repairReceipt.receipt.ticket_id,
    ).ticket.status,
  ).toBe("CLOSED");
});
