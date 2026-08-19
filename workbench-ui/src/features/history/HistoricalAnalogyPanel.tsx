import { ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { Panel } from "../../components/Panel";
import { useHistoricalAnalogiesQuery } from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";

const percent = (value?: number | null) => value == null ? "n/a" : `${(value * 100).toFixed(1)}%`;

export function HistoricalAnalogyPanel() {
  const { l, term } = useI18n();
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
    <Panel eyebrow={l("历史情境", "Historical Context")} title={l("相似风险状态", "Similar Risk States")}>
      {chart.length ? (
        <>
          <div className="chart-frame" aria-label={l("历史类比收益与回撤图", "Historical analogy return and drawdown chart")}>
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 12, right: 12, bottom: 8, left: 0 }}>
                <XAxis dataKey="drawdown" type="number" name={l("3个月回撤", "3m drawdown")} unit="%" />
                <YAxis dataKey="return3m" type="number" name={l("3个月收益", "3m return")} unit="%" />
                <ZAxis dataKey="similarity" range={[80, 360]} name={l("相似度", "similarity")} unit="%" />
                <Tooltip cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={chart} fill="#2c6e62" />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>{l("日期", "Date")}</th><th>{l("市场状态", "Regime")}</th><th>{l("相似度", "Similarity")}</th><th>{l("1个月", "1m")}</th><th>{l("3个月", "3m")}</th><th>{l("最大回撤", "Max DD")}</th></tr></thead>
              <tbody>{rows.map((item) => (
                <tr key={item.id}>
                  <td>{item.candidate_date.slice(0, 10)}</td><td>{term(item.regime)}</td>
                  <td>{percent(item.similarity)}</td><td>{percent(item.return_1m)}</td>
                  <td>{percent(item.return_3m)}</td><td>{percent(item.max_drawdown_3m)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </>
      ) : query.isError ? (
        <p className="muted">{l("历史情境暂时无法读取，本次研究不依赖该项继续展示。", "Historical context is temporarily unavailable; the main research result remains visible without it.")}</p>
      ) : query.isLoading ? (
        <p className="muted">{l("正在查找可用的历史相似情境…", "Finding usable historical analogies...")}</p>
      ) : (
        <p className="muted">{l("当前还没有找到可比较的历史风险状态；有匹配情境后会显示在这里。", "No comparable historical risk state is available yet; matching situations will appear here when found.")}</p>
      )}
    </Panel>
  );
}
