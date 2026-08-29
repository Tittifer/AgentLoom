import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    screenshot: "only-on-failure",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv run --locked uvicorn tests.e2e_app:app --host 127.0.0.1 --port 18000",
      cwd: "..",
      url: "http://127.0.0.1:18000/health",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 4173 --mode e2e",
      env: { VITE_API_TARGET: "http://127.0.0.1:18000" },
      url: "http://127.0.0.1:4173/colonies",
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
