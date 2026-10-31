import { test, expect } from "@playwright/test";
const headers = { "X-ESA-Request": "1" };
test("existing empty scope is truthful, binds explicitly and retries the same Deep turn", async ({
  page,
  request,
}) => {
  const c = await (
    await request.post("/api/conversations", {
      headers,
      data: { title: "空绑定恢复" },
    })
  ).json();
  await page.goto("/#/assistant?c=" + c.id);
  await expect(page.getByLabel("当前资料库")).toHaveValue("");
  await page.getByLabel("深入比较").check();
  await page.getByLabel("给助理发消息").fill("解释当前制度");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "重试这条消息" }),
  ).toBeVisible();
  const kb = await (
    await request.post("/api/library", {
      headers,
      data: { name: "补选测试库" },
    })
  ).json();
  await page.reload();
  await page.getByLabel("当前资料库").selectOption(kb.id);
  await expect
    .poll(
      async () =>
        (await (await request.get("/api/conversations/" + c.id)).json()).kb_id,
    )
    .toBe(kb.id);
  await page.getByRole("button", { name: "重试这条消息" }).click();
  await expect(page.getByText("UI外部回答替身，非实时模型。")).toBeVisible();
  const result = await (await request.get("/api/conversations/" + c.id)).json();
  expect(result.turns.filter((t: any) => t.role === "user")).toHaveLength(1);
  const runs = await (
    await request.get("/api/product/conversations/" + c.id + "/runs")
  ).json();
  expect(
    runs.every((r: any) => JSON.parse(r.input_json).detailed === true),
  ).toBeTruthy();
});

test("server history finds the first of 150 and supports archive/rename", async ({
  page,
  request,
}) => {
  let first: any;
  for (let i = 0; i < 150; i++) {
    const row = await (
      await request.post("/api/conversations", {
        headers,
        data: { title: "长期记录" + String(i).padStart(3, "0") },
      })
    ).json();
    if (i === 0) first = row;
  }
  await page.goto("/#/assistant");
  await page.getByLabel("搜索会话").fill("长期记录000");
  await page.getByRole("link", { name: "长期记录000", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(first.id));
  page.once("dialog", (d) => d.accept("改名后的历史"));
  await page.getByRole("button", { name: "重命名", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "改名后的历史" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "归档会话", exact: true }).click();
  await expect
    .poll(
      async () =>
        (await (await request.get("/api/conversations/" + first.id)).json())
          .archived,
    )
    .toBe(true);
});

test("A and B own separate runs; navigating and stopping B leave A running", async ({
  page,
  request,
}) => {
  const kb = await (
    await request.post("/api/library", {
      headers,
      data: { name: "并发测试库" },
    })
  ).json();
  const a = await (
    await request.post("/api/conversations", {
      headers,
      data: { title: "运行A", kb_id: kb.id },
    })
  ).json();
  const b = await (
    await request.post("/api/conversations", {
      headers,
      data: { title: "运行B", kb_id: kb.id },
    })
  ).json();
  const ra = await (
    await request.post(`/api/conversations/${a.id}/turns`, {
      headers,
      data: { message_id: "own-a", text: "UI等待A" },
    })
  ).json();
  await page.goto("/#/assistant?c=" + b.id);
  await expect(page.getByRole("button", { name: "停止本次执行" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "发送", exact: true }),
  ).toBeDisabled(); // empty composer only
  await page.getByLabel("给助理发消息").fill("UI等待B");
  await expect(
    page.getByRole("button", { name: "发送", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.getByRole("link", { name: "▥ 资料库", exact: true }).click();
  expect((await (await request.get("/api/runs/" + ra.id)).json()).status).toBe(
    "running",
  );
  await page.goto("/#/assistant?c=" + b.id);
  await page.getByRole("button", { name: "停止本次执行" }).click();
  await expect(page.getByRole("button", { name: "停止本次执行" })).toHaveCount(
    0,
  );
  expect((await (await request.get("/api/runs/" + ra.id)).json()).status).toBe(
    "running",
  );
  await request.post("/api/runs/" + ra.id + "/cancel", { headers, data: {} });
});

test("draft survives navigation, one composer, synthetic composition and narrow long text", async ({
  page,
}) => {
  await page.goto("/#/assistant");
  let sends = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/turns")) sends++;
  });
  const input = page.getByLabel("给助理发消息");
  await input.fill("未发送中文草稿");
  await input.dispatchEvent("compositionstart");
  await input.press("Enter");
  await input.dispatchEvent("compositionend");
  expect(sends).toBe(0);
  const draft = await input.inputValue();
  expect(draft.startsWith("未发送中文草稿")).toBeTruthy();
  await page.getByRole("link", { name: "▤ 我的事项", exact: true }).click();
  await page.getByRole("link", { name: "◌ 助理" }).click();
  await expect(page.getByLabel("给助理发消息")).toHaveValue(draft);
  await expect(page.locator("textarea")).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBeTruthy();
});
