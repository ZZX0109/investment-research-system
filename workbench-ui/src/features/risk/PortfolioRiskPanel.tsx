import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Panel } from "../../components/Panel";
import { usePortfolioRiskQuery } from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";

const percent = (value?: number | null) => value == null ? "n/a" : `${(value * 100).toFixed(1)}%`;

function scenarioLabel(name: string, language: "zh-CN" | "en-US") {
  const labels: Record<string, [string, string]> = {
    market_minus_10pct: ["市场整体下跌 10%（示例）", "Market -10% (illustrative)"],
    high_volatility: ["高波动示例（组合 -15%）", "High-volatility example (-15%)"],
    event_shock: ["事件冲击示例（组合 -8%）", "Event-shock example (-8%)"],
  };
  return labels[name]?.[language === "zh-CN" ? 0 : 1] ?? name.replaceAll("_", " ");
}

export function PortfolioRiskPanel() {
  const { l, language } = useI18n();
  const query = usePortfolioRiskQuery();
  const risk = query.data;
  const exposures = Object.entries(risk?.industry_exposure ?? {}).map(([name, value]) => ({ name, value: value * 100 }));
  const marginal = Object.entries(risk?.marginal_risk_contributions ?? {})
    .sort(([, left], [, right]) => Math.abs(right) - Math.abs(left))
    .slice(0, 5);
  const liquidity = Object.entries(risk?.liquidity_exposure ?? {})
    .sort(([, left], [, right]) => right - left)
    .slice(0, 5);
  if (!risk || risk.total_market_value <= 0) {
    return null;
  }
  return (
    <Panel eyebrow={l("组合风险", "Portfolio")} title={l("集中度与压力测试", "Concentration & Stress")}>
      {risk ? (
        <>
          <div className="metric-strip">
            <Metric label={l("组合市值", "Market value")} value={risk.total_market_value.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
            <Metric label="HHI" value={risk.concentration_hhi.toFixed(3)} />
            <Metric label={l("20日波动率", "20d volatility")} value={percent(risk.volatility_20d)} />
            <Metric label={l("最大回撤", "Max drawdown")} value={percent(risk.max_drawdown)} />
          </div>
          {exposures.length ? (
            <div className="chart-frame chart-frame--compact" aria-label={l("组合行业暴露图", "Portfolio industry exposure chart")}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={exposures} layout="vertical" margin={{ top: 4, right: 18, bottom: 4, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" unit="%" />
                  <YAxis dataKey="name" type="category" width={88} />
                  <Tooltip formatter={(value) => [`${Number(value).toFixed(1)}%`, l("暴露", "Exposure")]} />
                  <Bar dataKey="value" fill="#a85c35" radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : null}
          <div className="stress-grid">
            {Object.entries(risk.stress_scenarios).map(([name, value]) => (
              <div className="stress-row" key={name}><span>{scenarioLabel(name, language)}</span><strong>{value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong></div>
            ))}
          </div>
          <p className="muted">
            {language === "zh-CN"
              ? "以上压力情景是固定示例，用来帮助理解组合敏感度，不是历史事件重演，也不是模型预测。"
              : "These fixed stress scenarios are illustrative sensitivity examples, not historical replay or model predictions."}
          </p>
          {marginal.length || liquidity.length ? (
            <details className="research-technical-details">
              <summary>{l("查看边际风险与流动性", "View marginal risk and liquidity")}</summary>
              {marginal.length ? (
                <div className="stack-list">
                  <strong>{l("边际风险贡献（前五项）", "Top five marginal risk contributions")}</strong>
                  {marginal.map(([asset, value]) => <p key={`mrc-${asset}`}>{asset} · {percent(value)}</p>)}
                </div>
              ) : null}
              {liquidity.length ? (
                <div className="stack-list">
                  <strong>{l("流动性占用（持仓市值 / 近20日平均成交额）", "Liquidity usage (position value / 20d average traded value)")}</strong>
                  {liquidity.map(([asset, value]) => <p key={`liq-${asset}`}>{asset} · {value.toFixed(3)}x</p>)}
                </div>
              ) : null}
              <p className="muted">
                {language === "zh-CN"
                  ? `协方差矩阵已按实际交易日期对齐；${risk.stress_scenario_source ?? "illustrative_not_historical"}。`
                  : `Covariance is aligned on actual trading dates; source: ${risk.stress_scenario_source ?? "illustrative_not_historical"}.`}
              </p>
            </details>
          ) : null}
          {risk.warnings.map((warning) => <p className="muted" key={warning}>{warning}</p>)}
        </>
      ) : null}
    </Panel>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric-card"><div className="eyebrow">{label}</div><div className="metric-card__value">{value}</div></div>;
}
