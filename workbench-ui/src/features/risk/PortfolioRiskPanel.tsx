import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Panel } from "../../components/Panel";
import { usePortfolioRiskQuery } from "../../hooks/useWorkbenchQueries";

const percent = (value?: number | null) => value == null ? "n/a" : `${(value * 100).toFixed(1)}%`;

export function PortfolioRiskPanel() {
  const query = usePortfolioRiskQuery();
  const risk = query.data;
  const exposures = Object.entries(risk?.industry_exposure ?? {}).map(([name, value]) => ({ name, value: value * 100 }));
  return (
    <Panel eyebrow="Portfolio" title="Concentration & Stress">
      {risk ? (
        <>
          <div className="metric-strip">
            <Metric label="Market value" value={risk.total_market_value.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
            <Metric label="HHI" value={risk.concentration_hhi.toFixed(3)} />
            <Metric label="20d volatility" value={percent(risk.volatility_20d)} />
            <Metric label="Max drawdown" value={percent(risk.max_drawdown)} />
          </div>
          {exposures.length ? (
            <div className="chart-frame chart-frame--compact" aria-label="Portfolio industry exposure chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={exposures} layout="vertical" margin={{ top: 4, right: 18, bottom: 4, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" unit="%" />
                  <YAxis dataKey="name" type="category" width={88} />
                  <Tooltip formatter={(value) => [`${Number(value).toFixed(1)}%`, "Exposure"]} />
                  <Bar dataKey="value" fill="#a85c35" radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : null}
          <div className="stress-grid">
            {Object.entries(risk.stress_scenarios).map(([name, value]) => (
              <div className="stress-row" key={name}><span>{name.replaceAll("_", " ")}</span><strong>{value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong></div>
            ))}
          </div>
          {risk.warnings.map((warning) => <p className="muted" key={warning}>{warning}</p>)}
        </>
      ) : <p className="muted">Portfolio risk will appear after positions have real price series.</p>}
    </Panel>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric-card"><div className="eyebrow">{label}</div><div className="metric-card__value">{value}</div></div>;
}
