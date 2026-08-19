import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Panel } from "../../components/Panel";
import { useI18n } from "../../i18n";
import type { LongTermModelReading, PriceSeries } from "../../api/types";

type Period = { key: "1m" | "3m" | "1y" | "3y"; days: number; zh: string; en: string };

const PERIODS: Period[] = [
  { key: "1m", days: 21, zh: "近1个月", en: "1 month" },
  { key: "3m", days: 63, zh: "近3个月", en: "3 months" },
  { key: "1y", days: 252, zh: "近1年", en: "1 year" },
  { key: "3y", days: 756, zh: "近3年", en: "3 years" },
];

export function PriceTrendChart({ series, modelReadings, loading = false, error = false }: { series?: PriceSeries | null; modelReadings?: Record<string, LongTermModelReading> | null; loading?: boolean; error?: boolean }) {
  const { l } = useI18n();
  const [periodKey, setPeriodKey] = useState<Period["key"]>("1m");
  const period = PERIODS.find((item) => item.key === periodKey) ?? PERIODS[0];
  const points = useMemo(() => {
    const source = [...(series?.points ?? [])]
      .filter((point) => Number.isFinite(point.close) && point.close > 0)
      .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    const selected = source.slice(-period.days);
    const first = selected[0]?.close;
    const actual = selected.map((point) => ({
      date: point.timestamp.slice(0, 10),
      close: point.close,
      modelClose: null as number | null,
      changePct: first ? ((point.close / first) - 1) * 100 : 0,
    }));
    const last = actual.at(-1);
    if (!last || !modelReadings) return actual;
    const forecastPoints = [
      ["excess_return_120d", 120],
      ["excess_return_240d", 240],
    ] as const;
    const projected = forecastPoints
      .map(([task, days]) => {
        const reading = modelReadings[task];
        if (reading?.q50 == null) return null;
        const date = new Date(`${last.date}T00:00:00Z`);
        date.setUTCDate(date.getUTCDate() + days);
        return {
          date: date.toISOString().slice(0, 10),
          close: null as number | null,
          modelClose: Math.max(0.01, last.close * (1 + reading.q50)),
          changePct: null as number | null,
        };
      })
      .filter((point): point is { date: string; close: null; modelClose: number; changePct: null } => Boolean(point));
    return projected.length ? [...actual, { ...last, modelClose: last.close, close: last.close }, ...projected] : actual;
  }, [modelReadings, period.days, series]);
  const latest = [...points].reverse().find((point) => point.close != null);
  const first = points[0];
  const change = first && latest ? latest.changePct : null;

  return (
    <Panel
      eyebrow={l("价格走势", "Price trend")}
      title={l(`最近${period.zh.replace("近", "")}的收盘变化`, `${period.en} closing-price change`)}
      actions={
        <div className="stock-workspace__period-tabs" role="tablist" aria-label={l("价格走势周期", "Price trend period")}>
          {PERIODS.map((item) => (
            <button key={item.key} type="button" role="tab" aria-selected={item.key === periodKey} className={item.key === periodKey ? "stock-workspace__period-tab is-active" : "stock-workspace__period-tab"} onClick={() => setPeriodKey(item.key)}>
              {l(item.zh, item.en)}
            </button>
          ))}
        </div>
      }
    >
      {loading ? <p className="stock-workspace__empty">{l("正在读取价格曲线…", "Loading the price trend…")}</p> : null}
      {!loading && error ? <p className="stock-workspace__empty">{l("价格曲线暂时无法读取，请稍后重试。", "The price trend is temporarily unavailable. Try again later.")}</p> : null}
      {!loading && !error && !points.length ? <p className="stock-workspace__empty">{l("暂无本地行情序列。", "No local price series is available.")}</p> : null}
      {!loading && !error && points.length ? (
        <>
          <div className="stock-workspace__trend-meta">
            <span>{l("最新收盘", "Latest close")} <strong>{latest?.close != null ? latest.close.toFixed(2) : "—"}</strong></span>
            <span className={change != null && change < 0 ? "is-negative" : "is-positive"}>
              {l("区间变化", "Period change")} <strong>{change != null ? `${change >= 0 ? "+" : ""}${change.toFixed(2)}%` : "—"}</strong>
            </span>
          </div>
          <div className="chart-frame stock-workspace__trend-chart" aria-label={l("价格走势折线图", "Price trend line chart")}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" minTickGap={28} />
                <YAxis domain={["auto", "auto"]} width={64} tickFormatter={(value) => Number(value).toFixed(0)} />
                <Tooltip formatter={(value, name) => [name === "close" ? Number(value).toFixed(2) : Number(value).toFixed(2), name === "close" ? l("实际收盘", "Actual close") : l("模型参考走势", "Model reference path")]} />
                <Line type="monotone" dataKey="close" name="close" stroke="#2864dc" dot={false} strokeWidth={2.5} connectNulls={false} />
                <Line type="monotone" dataKey="modelClose" name="modelClose" stroke="#9b6bce" dot={false} strokeWidth={2.5} strokeDasharray="6 5" connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="stock-workspace__trend-legend" aria-label={l("价格走势图例", "Price trend legend")}>
            <span><i className="stock-workspace__trend-legend-swatch is-actual" />{l("实际收盘", "Actual close")}</span>
            <span><i className="stock-workspace__trend-legend-swatch is-model" />{l("模型参考走势（6/12个月）", "Model reference path (6/12m)")}</span>
          </div>
          <p className="stock-workspace__trend-note">{l("蓝线是历史收盘价，紫色虚线是长期模型基于 6/12 个月相对表现的参考路径；仅作研究观察，不是买卖建议。", "Blue is the historical close; the purple dashed line is a long-term model reference path based on 6/12-month relative performance. It is for research observation, not trading advice.")}</p>
        </>
      ) : null}
    </Panel>
  );
}
