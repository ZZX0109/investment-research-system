import path from "node:path";
import { execFileSync } from "node:child_process";
import { chromium } from "playwright";
import { beforeAll, describe, expect, it } from "vitest";

const rootDir = path.resolve(__dirname, "..");
const viteBin = path.join(rootDir, "node_modules", "vite", "bin", "vite.js");
const builtIndexPath = path.join(rootDir, "dist-workbench", "index.html");
const builtIndexUrl = `file://${builtIndexPath}`;

describe("workbench single merged interface e2e", () => {
  beforeAll(() => {
    execFileSync(process.execPath, [viteBin, "build", "--config", "workbench-ui/vite.config.ts"], {
      cwd: rootDir,
      stdio: "pipe"
    });
  // Vite's production bundle can take longer on a cold cache while the
  // backend is doing its local snapshot work; this is a build timeout rather
  // than a UI assertion timeout.
  }, 60_000);

  it("renders the merged 选股·仪表盘·AI + professional workbench on one screen", async () => {
    const browser = await chromium.launch({ headless: true, args: ["--allow-file-access-from-files"] });
    const page = await browser.newPage();
    page.setDefaultTimeout(10_000);

    try {
      await page.goto(builtIndexUrl, { waitUntil: "domcontentloaded" });

      // One screen — no view tabs. The long-term AI assistant hero leads.
      await page.getByRole("heading", { name: "长期投资 AI 研究助手" }).waitFor({ state: "visible" });

      // The compliance banner is present.
      await page.getByText(/不输出买卖、加仓、减仓、目标价或收益承诺/).waitFor({ state: "visible" });
      await page.getByText(/研究观察 · 非投资建议/).waitFor({ state: "visible" });

      // Asset picker panel (选股 eyebrow; the details-collapsed professional
      // workbench would otherwise collide on common terms like 研究对象).
      await page.getByText("选股", { exact: true }).waitFor({ state: "visible" });
      // The single-source dashboard panel mounts (eyebrow renders in both the
      // loading and empty states; data-driven tiles are covered by the backend
      // snapshot tests, so the e2e only pins the structural mount).
      await page.getByText("仪表盘", { exact: true }).waitFor({ state: "visible" });

      // The multi-turn AI panel: heading + three example questions + compose box.
      await page.getByRole("heading", { name: "向研究助手提问" }).waitFor({ state: "visible" });
      await page.getByRole("button", { name: "请解释这家公司最近经营发生了什么变化" }).waitFor({ state: "visible" });
      await page.getByRole("button", { name: "如果我长期关注这家公司，主要风险是什么" }).waitFor({ state: "visible" });
      await page.getByRole("button", { name: "基本面看起来不错，但不同观察周期结果不一致，为什么" }).waitFor({ state: "visible" });
      await page.getByRole("textbox", { name: "提问" }).waitFor({ state: "visible" });
      await page.getByRole("button", { name: "提问" }).waitFor({ state: "visible" });

      // The five-section plain-answer structure is introduced before any run.
      await page.getByText("经营情况", { exact: false }).waitFor({ state: "visible" });
      await page.getByText("长期变化", { exact: false }).waitFor({ state: "visible" });
      await page.getByText("可能的风险", { exact: false }).waitFor({ state: "visible" });
      await page.getByText("还需观察", { exact: false }).waitFor({ state: "visible" });
      await page.getByText("依据和更新时间", { exact: false }).waitFor({ state: "visible" });

      // The product shell makes research workflow, data freshness and trust
      // state visible without opening a secondary professional app.
      await page.getByRole("tab", { name: "数据中心" }).click();
      await page.getByRole("heading", { name: "数据截止、覆盖率与质量状态" }).waitFor({ state: "visible" });
      await page.getByRole("tab", { name: "信任中心" }).click();
      await page.getByRole("heading", { name: "为什么可以相信、哪里不能相信" }).waitFor({ state: "visible" });
      await page.getByRole("tab", { name: "设置" }).click();
      await page.getByRole("heading", { name: "研究边界与项目配置" }).waitFor({ state: "visible" });
      await page.getByRole("button", { name: "打开项目 AI 设置" }).waitFor({ state: "visible" });
      await page.getByRole("tab", { name: "今日" }).click();
      await page.getByText("仪表盘", { exact: true }).waitFor({ state: "visible" });

      // The short-term supporting view stays in the dashboard. The dedicated
      // knowledge and technical drawers are intentionally hidden so the right
      // column remains a focused chat surface.
      await page.getByText("短期市场观察", { exact: false }).first().waitFor({ state: "visible" });
      expect(await page.getByText("知识库依据", { exact: false }).count()).toBe(0);
      expect(await page.getByText("技术与审计详情", { exact: false }).count()).toBe(0);

      // The entertainment-only personality lab is isolated behind the mode
      // switch and defaults to the new delayed-quote daily paper game.
      await page.getByRole("button", { name: /研究观察 · 非投资建议/ }).click();
      await page.getByRole("heading", { name: "认识投资习惯，也可以参加今日模拟赛" }).waitFor({ state: "visible" });
      await page.getByRole("button", { name: "今日模拟赛", exact: true }).waitFor({ state: "visible" });
      await page.getByRole("button", { name: "16题人格测试", exact: true }).waitFor({ state: "visible" });
      await page.getByRole("button", { name: "30日历史回放", exact: true }).waitFor({ state: "visible" });
      await page.getByRole("button", { name: "返回研究面板" }).click();

      // English toggle still works (one shared language switch in the header).
      await page.getByTestId("language-switch-en-US").click();
      await page.getByRole("heading", { name: "Long-term investment AI research assistant" }).waitFor({ state: "visible" });
    } finally {
      await page.close();
      await browser.close();
    }
  }, 30_000);
});
