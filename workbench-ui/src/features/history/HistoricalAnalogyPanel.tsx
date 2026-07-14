import { ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { Panel } from "../../components/Panel";
import { useHistoricalAnalogiesQuery } from "../../hooks/useWorkbenchQueries";
import { useWorkbenchStore } from "../../state/workbenchStore";

const percent = (value?: number | null) => value == null ? "n/a" : `${(value * 100).toFixed(1)}%`;

export function HistoricalAnalogyPanel() {
  const assetId = useWorkbenchStore((state) => state.selectedAssetId);
  const query = useHistoricalAnalogiesQuery(assetId);
  const rows = query.data ?? [];
  const chart = rows.map((item) => ({
    date: item.candidate_date.slice(0, 10),
    return3m: (item.return_3m ?? 0) * 100,
    drawdown: (item.max_drawdown_3m ?? 0) * 100,
    similarity: item.similarity * 100,
    regime: item.regime
  }));

  return (
    <Panel eyebrow="Historical Context" title="Similar Risk States">
      {chart.length ? (
        <>
          <div className="chart-frame" aria-label="Historical analogy return and drawdown chart">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 12, right: 12, bottom: 8, left: 0 }}>
                <XAxis dataKey="drawdown" type="number" name="3m drawdown" unit="%" />
                <YAxis dataKey="return3m" type="number" name="3m return" unit="%" />
                <ZAxis dataKey="similarity" range={[80, 360]} name="similarity" unit="%" />
                <Tooltip cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={chart} fill="#2c6e62" />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>Date</th><th>Regime</th><th>Similarity</th><th>1m</th><th>3m</th><th>Max DD</th></tr></thead>
              <tbody>{rows.map((item) => (
                <tr key={item.id}>
                  <td>{item.candidate_date.slice(0, 10)}</td><td>{item.regime}</td>
                  <td>{percent(item.similarity)}</td><td>{percent(item.return_1m)}</td>
                  <td>{percent(item.return_3m)}</td><td>{percent(item.max_drawdown_3m)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </>
      ) : <p className="muted">No leakage-safe historical matches are available for the selected asset.</p>}
    </Panel>
  );
}
