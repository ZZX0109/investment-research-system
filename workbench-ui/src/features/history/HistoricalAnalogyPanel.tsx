import { useMemo, useState } from "react";
import { ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { Panel } from "../../components/Panel";
import { useHistoricalAnalogiesQuery, usePriceSeriesQuery } from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";

const percent = (value?: number | null) => value == null ? "n/a" : `${(value * 100).toFixed(1)}%`;

/** A daily close point restricted to the fields the analogy window needs. */
type PricePoint = { timestamp: string; close: number };

/**
 * Round 35 — click a scatter point (a historical similar-risk moment) to see
 * the realized price path around that candidate date: ~20 trading days
 * before and ~63 after, with reference lines marking the candidate date and
 * the +1m / +3m outcome horizons. Lets the user visually verify "what
 * actually happened the last time the stock looked like this".
 */
function AnalogyDetailChart({ points, candidateDate, row }: {
  points: PricePoint[];
  candidateDate: string;
  row: { candidate_date: string; similarity: number; regime: string; return_1m?: number | null; return_3m?: number | null; max_drawdown_3m?: number | null };
}) {
  const { l } = useI18n();
  const window = useMemo(() => {
    const target = candidateDate.slice(0, 10);
    const idx = points.findIndex((p) => p.timestamp.slice(0, 10) === target);
    if (idx < 0) return null;
    const start = Math.max(0, idx - 20);
    const end = Math.min(points.length, idx + 64); // +63 trading days ≈ 3m
    const slice = points.slice(start, end).map((p) => ({
      date: p.timestamp.slice(0, 10),
      close: p.close,
      isCandidate: p.timestamp.slice(0, 10) === target,
      is1m: points[idx + 21] && p.timestamp.slice(0, 10) === points[idx + 21].timestamp.slice(0, 10),
      is3m: points[idx + 63] && p.timestamp.slice(0, 10) === points[idx + 63].timestamp.slice(0, 10),
    }));
    return { slice, candidateIdx: idx - start, plus1mIdx: idx + 21 - start, plus3mIdx: idx + 63 - start };
  }, [points, candidateDate]);

  if (!window) {
    return <p className="muted">{l("该历史情境在价格序列中无对应点。", "No matching point in the price series for this scenario.")}</p>;
  }
  const candDate = window.slice[window.candidateIdx]?.date;
  const m1Date = window.slice[window.plus1mIdx]?.date;
  const m3Date = window.slice[window.plus3mIdx]?.date;
  return (
    <div className="chart-frame" aria-label={l("历史情境价格窗口", "Historical scenario price window")} style={{ height: 200 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={window.slice} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
          <XAxis dataKey="date" tick={{ fontSize: 10 }} interval={Math.floor(window.slice.length / 6)} />
          <YAxis domain={["auto", "auto"]} tick={{ fontSize: 10 }} width={48} />
          <Tooltip formatter={(value: unknown) => Number(value).toFixed(2)} labelFormatter={(label) => String(label)} />
          <ReferenceLine x={candDate} stroke="#2c6e62" strokeDasharray="4 4" label={{ value: l("情境起点", "scenario"), fontSize: 10, fill: "#2c6e62" }} />
          {m1Date ? <ReferenceLine x={m1Date} stroke="#9b6bce" strokeDasharray="3 3" label={{ value: `1m ${percent(row.return_1m)}`, fontSize: 10, fill: "#9b6bce" }} /> : null}
          {m3Date ? <ReferenceLine x={m3Date} stroke="#c2548b" strokeDasharray="3 3" label={{ value: `3m ${percent(row.return_3m)}`, fontSize: 10, fill: "#c2548b" }} /> : null}
          <Line type="monotone" dataKey="close" stroke="#2c6e62" dot={false} strokeWidth={1.5} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="muted" style={{ marginTop: 6 }}>
        {l(`相似度 ${percent(row.similarity)} · 市场状态 ${row.regime} · 最大回撤 ${percent(row.max_drawdown_3m)}`, `similarity ${percent(row.similarity)} · regime ${row.regime} · max drawdown ${percent(row.max_drawdown_3m)}`)}
      </p>
    </div>
  );
}

export function HistoricalAnalogyPanel() {
  const { l, term } = useI18n();
  const assetId = useWorkbenchStore((state) => state.selectedAssetId);
  const query = useHistoricalAnalogiesQuery(assetId);
  const priceSeries = usePriceSeriesQuery(assetId);
  const rows = query.data ?? [];
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const chart = rows.map((item) => ({
    date: item.candidate_date.slice(0, 10),
    return3m: (item.return_3m ?? 0) * 100,
    drawdown: (item.max_drawdown_3m ?? 0) * 100,
    similarity: item.similarity * 100,
    regime: item.regime
  }));

  const pricePoints: PricePoint[] = useMemo(() => {
    const series = priceSeries.data?.find((s) => s.series_role === "asset") ?? priceSeries.data?.[0] ?? null;
    if (!series?.points) return [];
    return series.points
      .filter((p) => typeof p.close === "number" && p.close > 0)
      .map((p) => ({ timestamp: p.timestamp, close: p.close as number }))
      .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }, [priceSeries.data]);

  const selectedRow = selectedDate ? rows.find((r) => r.candidate_date.slice(0, 10) === selectedDate) : null;

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
                <Scatter
                  data={chart}
                  fill="#2c6e62"
                  onClick={(payload: any) => {
                    const date = payload?.date;
                    if (typeof date === "string") setSelectedDate(date);
                  }}
                  cursor="pointer"
                />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <p className="muted" style={{ marginTop: 6 }}>{l("点击散点查看该历史情境前后的价格走势。", "Click a point to see the price path around that historical moment.")}</p>
          {selectedRow && selectedDate ? (
            <div style={{ marginTop: 8, padding: 8, border: "1px solid var(--border, #ddd)", borderRadius: 6 }}>
              <AnalogyDetailChart points={pricePoints} candidateDate={selectedDate} row={selectedRow} />
            </div>
          ) : null}
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th>{l("日期", "Date")}</th><th>{l("市场状态", "Regime")}</th><th>{l("相似度", "Similarity")}</th><th>{l("1个月", "1m")}</th><th>{l("3个月", "3m")}</th><th>{l("最大回撤", "Max DD")}</th></tr></thead>
              <tbody>{rows.map((item) => (
                <tr
                  key={item.id}
                  onClick={() => setSelectedDate(item.candidate_date.slice(0, 10))}
                  style={{ cursor: "pointer", background: selectedDate === item.candidate_date.slice(0, 10) ? "var(--accent-bg, #f0f7f5)" : undefined }}
                >
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
