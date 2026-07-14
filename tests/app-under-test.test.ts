import { readFileSync } from "node:fs";
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import path from "node:path";
import { describe, expect, it } from "vitest";

const rootDir = path.resolve(__dirname, "..");

function readFixture(relativePath: string) {
  return readFileSync(path.join(rootDir, relativePath), "utf8");
}

describe("local app-under-test fixtures", () => {
  it("ships browser scripts that parse before the app is tested", () => {
    execFileSync(process.execPath, ["--check", path.join(rootDir, "app-under-test/public/app.js")]);
  });

  it("publishes the scenario hooks expected by onboarding and selectors", () => {
    const loginHtml = readFixture("app-under-test/public/login.html");
    const formHtml = readFixture("app-under-test/public/create-form.html");
    const tasksHtml = readFixture("app-under-test/public/tasks.html");
    const appScript = readFixture("app-under-test/public/app.js");
    const seed = readFixture("app-under-test/data/seed.json");

    expect(loginHtml).toContain('data-testid="login-submit"');
    expect(formHtml).toContain('data-testid="order-submit"');
    expect(formHtml).toContain('data-testid="order-validation-error"');
    expect(tasksHtml).toContain('data-testid="task-filter-completed"');
    expect(tasksHtml).toContain('data-testid="task-search-input"');
    expect(tasksHtml).toContain('data-testid="task-empty-state"');
    expect(tasksHtml).toContain('data-testid="task-error-trigger"');
    expect(appScript).toContain('data-testid="ship-order-${order.id}"');
    expect(appScript).toContain("/api/tasks");
    expect(appScript).toContain("/api/orders");
    expect(seed).toContain('"id": "ord-1001"');
    expect(seed).toContain('"id": "task-04"');
  });

  it("keeps the target app independent from Agent demo APIs", () => {
    const appFiles = [
      "app-under-test/server.mjs",
      "app-under-test/public/app.js",
      "app-under-test/public/login.html",
      "app-under-test/public/tasks.html",
      "app-under-test/data/seed.json"
    ].map(readFixture).join("\n");

    expect(appFiles).not.toContain("AGENT_URL");
    expect(appFiles).not.toContain("/api/demo/tasks");
    expect(appFiles).not.toContain("/api/v1/test-officer");
    expect(appFiles).toContain("/api/tasks");
    expect(appFiles).toContain("/api/orders");
  });

  it("serves seed-backed tasks and orders from its own app server", async () => {
    const port = 4600 + Math.floor(Math.random() * 500);
    const server = spawn(process.execPath, ["app-under-test/server.mjs"], {
      cwd: rootDir,
      env: {
        ...process.env,
        APP_UNDER_TEST_PORT: String(port)
      },
      stdio: ["ignore", "pipe", "pipe"]
    });
    try {
      await waitUntilReady(`http://127.0.0.1:${port}`);
      const active = await fetchJson(`http://127.0.0.1:${port}/api/tasks?status=active`);
      const completedWithBug = await fetchJson(`http://127.0.0.1:${port}/api/tasks?status=completed`);
      const completedFixed = await fetchJson(`http://127.0.0.1:${port}/api/tasks?status=completed&fixtureBug=0`);
      const urgent = await fetchJson(`http://127.0.0.1:${port}/api/tasks?keyword=urgent`);
      const orders = await fetchJson(`http://127.0.0.1:${port}/api/orders`);
      const errorResponse = await fetch(`http://127.0.0.1:${port}/api/tasks?status=error`);

      expect(active.tasks.map((task: { status: string }) => task.status)).toEqual(["active", "active"]);
      expect(completedWithBug.tasks.some((task: { status: string }) => task.status === "active")).toBe(true);
      expect(completedFixed.tasks.map((task: { status: string }) => task.status)).toEqual(["completed", "completed"]);
      expect(urgent.tasks[0]?.title).toContain("urgent");
      expect(orders.orders[0]?.id).toBe("ord-1001");
      expect(errorResponse.status).toBe(500);
    } finally {
      await stopServer(server);
    }
  });

  it("provides an onboarding example for the local target app", () => {
    const onboarding = JSON.parse(
      readFixture("examples/onboarding/local-demo-app.json")
    ) as {
      baseUrl: string;
      keyPages: Array<{ path: string }>;
      selectorHints: Array<{ id: string; queries: string[] }>;
      scenarioRequests: Array<{ family: string }>;
    };

    expect(onboarding.baseUrl).toBe("http://127.0.0.1:4173");
    expect(onboarding.keyPages.map((page) => page.path)).toContain("/orders/create-form");
    expect(onboarding.selectorHints.find((hint) => hint.id === "task-filter-completed")?.queries).toContain(
      "data-testid=task-filter-completed"
    );
    expect(onboarding.selectorHints.find((hint) => hint.id === "task-search-input")?.queries).toContain(
      "data-testid=task-search-input"
    );
    expect(onboarding.scenarioRequests.map((scenario) => scenario.family)).toEqual(
      expect.arrayContaining(["auth-login", "golden-path", "form-submission", "list-state-change"])
    );
  });
});

async function fetchJson(url: string) {
  const response = await fetch(url);
  expect(response.ok).toBe(true);
  return response.json() as Promise<{
    tasks?: Array<{ id: string; title: string; status: string }>;
    orders?: Array<{ id: string; customer: string; status: string }>;
  }>;
}

async function waitUntilReady(url: string) {
  const deadline = Date.now() + 5_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { redirect: "manual" });
      if (response.status >= 200 && response.status < 500) {
        return;
      }
    } catch {
      // Retry until the server starts accepting connections.
    }
    await delay(100);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function stopServer(server: ChildProcess) {
  if (server.exitCode !== null) {
    return;
  }
  server.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => server.once("close", resolve)),
    delay(500).then(() => {
      if (server.exitCode === null) {
        server.kill("SIGKILL");
      }
    })
  ]);
}

function delay(milliseconds: number) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}
