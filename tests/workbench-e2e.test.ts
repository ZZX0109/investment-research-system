import path from "node:path";
import { execFileSync } from "node:child_process";
import { chromium } from "playwright";
import { beforeAll, describe, expect, it } from "vitest";

const rootDir = path.resolve(__dirname, "..");
const viteBin = path.join(rootDir, "node_modules", "vite", "bin", "vite.js");
const builtIndexPath = path.join(rootDir, "dist-workbench", "index.html");
const builtIndexUrl = `file://${builtIndexPath}`;

describe("workbench fixed-path e2e", () => {
  beforeAll(() => {
    execFileSync(process.execPath, [viteBin, "build", "--config", "workbench-ui/vite.config.ts"], {
      cwd: rootDir,
      stdio: "pipe"
    });
  }, 30_000);

  it("replays the seeded demo workbench path from asset selection into fixed run context", async () => {
    const browser = await chromium.launch({ headless: true, args: ["--allow-file-access-from-files"] });
    const page = await browser.newPage();
    page.setDefaultTimeout(10_000);

    try {
      await page.goto(builtIndexUrl, { waitUntil: "domcontentloaded" });

      await page.getByRole("heading", { name: "A股量化研究平台" }).waitFor({ state: "visible" });
      await page.getByTestId("mode-switch-research").waitFor({ state: "visible" });
      await page.getByText("研究级公开数据 · 非投资建议 · 不可直接交易 · 免费数据产物永不进入正式发布").waitFor({ state: "visible" });
      await page.getByTestId("mode-switch-demo").click();
      await page.getByTestId("mode-switch-demo").waitFor({ state: "visible" });

      await page.getByTestId("asset-card-nvda").click();

      await page.getByTestId("selected-run-context").waitFor({ state: "visible" });
      expect(await page.getByTestId("selected-run-context").textContent()).toContain("NVDA");
      await page.getByTestId("selected-run-dossier").first().waitFor({ state: "visible" });
      await page.getByRole("heading", { name: "Run Lineage" }).waitFor({ state: "visible" });

      await page.getByTestId("toggle-run-scoped-research").click();
      await page.getByText("Run-Scoped Research").waitFor({ state: "visible" });
      await page.getByText("Frozen run bundle with immutable report output").waitFor({ state: "visible" });
    } finally {
      await page.close();
      await browser.close();
    }
  }, 30_000);
});
