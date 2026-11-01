import { test, expect } from "@playwright/test";
const headers = { "X-ESA-Request": "1" };

for (const failure of [false, true])
  test(
    "a delayed " +
      (failure ? "failed" : "successful") +
      " send stays with its original conversation",
    async ({ page, request }) => {
      const kb = await (
        await request.post("/api/library", {
          headers,
          data: { name: "异步归属合成" },
        })
      ).json();
      const a = await (
        await request.post("/api/conversations", {
          headers,
          data: { title: "发送中的A", kb_id: kb.id },
        })
      ).json();
      const b = await (
        await request.post("/api/conversations", {
          headers,
          data: { title: "正在查看的B", kb_id: kb.id },
        })
      ).json();
      await page.goto("/#/assistant?c=" + b.id);
      await page
        .getByRole("textbox", { name: "给助理发消息" })
        .fill("B的草稿保留");
      await page.locator(`a[href="#/assistant?c=${a.id}"]`).click();
      let release!: () => void, reached!: () => void;
      const held = new Promise<void>((r) => (release = r)),
        pending = new Promise<void>((r) => (reached = r));
      await page.route(
        "**/api/conversations/" + a.id + "/turns",
        async (route) => {
          const response = await route.fetch();
          reached();
          await held;
          if (failure)
            await route.fulfill({
              status: 503,
              contentType: "application/json",
              body: JSON.stringify({
                error: {
                  code: "SIMULATED_SEND_FAILURE",
                  message: "仅属于A的模拟网络错误",
                },
              }),
            });
          else await route.fulfill({ response });
        },
      );
      try {
        await page
          .getByRole("textbox", { name: "给助理发消息" })
          .fill("明确的合成只读问题");
        await page.getByRole("button", { name: "发送", exact: true }).click();
        await pending;
        await page.locator(`a[href="#/assistant?c=${b.id}"]`)
          .click();
        const delivered = page.waitForResponse(
          (r) =>
            r.request().method() === "POST" &&
            r.url().endsWith("/" + a.id + "/turns"),
        );
        release();
        await delivered;
        await expect(
          page.getByRole("textbox", { name: "给助理发消息" }),
        ).toBeEnabled();
        await expect(page).toHaveURL(new RegExp(b.id));
        await expect(
          page.getByRole("textbox", { name: "给助理发消息" }),
        ).toHaveValue("B的草稿保留");
        await expect(page.getByRole("alert")).toHaveCount(0);
        if (failure) {
          await page.locator(`a[href="#/assistant?c=${a.id}"]`)
            .click();
          await expect(page.getByRole("alert")).toBeVisible();
          await page.getByRole("alert").getByText("查看原因", {exact:true}).click();
          await expect(page.getByText(/仅属于A的模拟网络错误/)).toBeVisible();
        }
        expect(
          (await (await request.get("/api/conversations/" + a.id)).json()).turns
            .length,
        ).toBeGreaterThan(0);
      } finally {
        release();
      }
    },
  );

for (const destination of ["conversation", "requests"])
  test(
    "task creation respects the current " +
      destination +
      " after its response is delayed",
    async ({ page, request }) => {
      const a = await (
        await request.post("/api/conversations", {
          headers,
          data: { title: "创建中切换页面" },
        })
      ).json();
      const b = await (
        await request.post("/api/conversations", {
          headers,
          data: { title: "创建后仍查看B" },
        })
      ).json();
      await page.goto("/#/assistant?c=" + a.id);
      let release!: () => void, reached!: () => void;
      let created: any;
      const held = new Promise<void>((r) => (release = r)),
        pending = new Promise<void>((r) => (reached = r));
      await page.route("**/api/tasks", async (route) => {
        if (route.request().method() !== "POST") return route.continue();
        const response = await route.fetch();
        created = await response.json();
        reached();
        await held;
        await route.fulfill({ response });
      });
      try {
        await page
          .getByRole("button", { name: "借用电脑", exact: true })
          .click();
        await page
          .getByRole("button", { name: "按所选范围开始", exact: true })
          .click();
        await pending;
        await page.keyboard.press("Escape");
        if (destination === "requests")
          await page
            .getByRole("link", { name: "▤ 我的事项", exact: true })
            .click();
        else
          await page.locator(`a[href="#/assistant?c=${b.id}"]`)
            .click();
        const refreshed = page.waitForResponse(
          (r) =>
            r.request().method() === "GET" &&
            r.url().includes("/api/conversations/page"),
        );
        release();
        await refreshed;
        await page.evaluate(
          () =>
            new Promise((resolve) =>
              requestAnimationFrame(() => requestAnimationFrame(resolve)),
            ),
        );
        if (destination === "requests")
          await expect(page).toHaveURL(/#\/requests$/);
        else await expect(page).toHaveURL(new RegExp(b.id));
        await expect(page.getByRole("dialog")).toHaveCount(0);
        expect(
          (await (await request.get("/api/tasks/" + created.task_id)).json())
            .facts,
        ).toEqual({});
      } finally {
        release();
      }
    },
  );
