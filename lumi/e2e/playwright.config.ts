import { defineConfig } from "@playwright/test";

// Real Django (e2e/server.py, simulated providers) + real Vite dev server. Chrome from the box,
// so no browser download. Run: cd lumi/e2e && npm test  (needs DATABASE_URL, see devenv.sh).
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  workers: 1,
  reporter: [["list"]],
  outputDir: "./test-results",
  use: {
    baseURL: "http://localhost:3010",
    channel: "chrome",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "uv run python e2e/server.py",
      cwd: "..",
      url: "http://localhost:8000/health",
      timeout: 90_000,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --host localhost --strictPort",
      cwd: "../frontend",
      url: "http://localhost:3010",
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
