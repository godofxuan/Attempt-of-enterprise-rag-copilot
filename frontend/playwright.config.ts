import { defineConfig } from "@playwright/test";
import path from "node:path";
const port = Number(process.env.ESA_UI_TEST_PORT || 8771);
const root = path.resolve(import.meta.dirname, "..");
const python =
  process.env.ESA_TEST_PYTHON ||
  (process.platform === "win32"
    ? path.join(root, ".venv/Scripts/python.exe")
    : "python");
export default defineConfig({
  testDir: "./tests",
  timeout: 30000,
  workers: 1,
  retries: 0,
  outputDir: "../.private/esa-vnext/upgrade-061-070/browser",
  reporter: [
    ["list"],
    [
      "json",
      {
        outputFile:
          "../.private/esa-vnext/upgrade-061-070/browser-results.json",
      },
    ],
  ],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    headless: true,
    channel:
      process.env.ESA_BROWSER_CHANNEL ||
      (process.platform === "win32" ? "msedge" : undefined),
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `"${python}" -B -X utf8 "${path.join(root, "tests/product/browser_server.py")}" --port ${port}`,
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: false,
    timeout: 30000,
  },
});
