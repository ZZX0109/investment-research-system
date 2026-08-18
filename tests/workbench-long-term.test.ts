import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LongTermInvestorSummary } from "../workbench-ui/src/features/research/LongTermInvestorSummary";

describe("long-term investor summary", () => {
  it("fails closed and keeps the novice workflow visible when no evidence is available", () => {
    const html = renderToStaticMarkup(
      createElement(LongTermInvestorSummary, { language: "zh-CN" }),
    );

    expect(html).toContain("给长期投资者的一分钟摘要");
    expect(html).toContain("证据不足");
    expect(html).toContain("支持与反方证据");
    expect(html).toContain("接下来观察什么");
    expect(html).toContain("什么会推翻当前判断");
    expect(html).toContain("先补数据");
    expect(html).toContain("不应把研究参考当成确定结论");
  });

  it("preserves the same safe flow in English", () => {
    const html = renderToStaticMarkup(
      createElement(LongTermInvestorSummary, { language: "en-US" }),
    );

    expect(html).toContain("One-minute summary for long-term investors");
    expect(html).toContain("Evidence limited");
    expect(html).toContain("Evidence for / against");
    expect(html).toContain("What to watch next");
    expect(html).toContain("What could overturn this view");
    expect(html).toContain("Fix data first");
  });

  it("shows all four long-term model readings without turning them into a trade instruction", () => {
    const html = renderToStaticMarkup(
      createElement(LongTermInvestorSummary, {
        language: "zh-CN",
        scorecard: {
          schema_version: "long-term-scorecard-response-v1",
          data_tier: "research_pit",
          deployment_ready: false,
          symbol: "600000",
          status: "available",
          blocking_reasons: [],
          long_term_model_readings: {
            excess_return_120d: { q10: -0.08, q50: 0.03, q90: 0.14 },
            excess_return_240d: { q10: -0.12, q50: 0.06, q90: 0.21 },
            future_max_drawdown_120d: { q10: -0.32, q50: -0.18, q90: -0.08 },
            future_max_drawdown_240d: { q10: -0.41, q50: -0.23, q90: -0.11 },
          },
        },
      }),
    );

    expect(html).toContain("相对表现（约6个月）");
    expect(html).toContain("相对表现（约12个月）");
    expect(html).toContain("潜在回撤（约6个月）");
    expect(html).toContain("潜在回撤（约12个月）");
    expect(html).toContain("专业详情（默认折叠）");
    expect(html).not.toContain("建议买入");
  });

  it("does not present a complete long-term view before all model readings exist", () => {
    const html = renderToStaticMarkup(
      createElement(LongTermInvestorSummary, {
        language: "zh-CN",
        scorecard: {
          schema_version: "long-term-scorecard-response-v1",
          data_tier: "research_pit",
          deployment_ready: false,
          symbol: "600000",
          status: "available",
          blocking_reasons: [],
          scorecard: { long_term_quality: 72 },
        },
      }),
    );

    expect(html).toContain("等待模型读数");
    expect(html).toContain("四个长期模型读数尚待生成");
  });
});
