import { useMemo, useRef, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Panel } from "../../components/Panel";
import { useI18n } from "../../i18n";
import type { LongTermModelReading, PricePathForecast, PriceSeries } from "../../api/types";

type Period = { key: "1m" | "3m" | "1y" | "3y"; days: number; zh: string; en: string };
const PERIODS: Period[] = [
  { key: "1m", days: 21, zh: "近1个月", en: "1 month" },
  { key: "3m", days: 63, zh: "近3个月", en: "3 months" },
  { key: "1y", days: 252, zh: "近1年", en: "1 year" },
  { key: "3y", days: 756, zh: "近3年", en: "3 years" },
];

type TrendPoint = {
  date: string;
  close: number | null;
  modelClose: number | null;
  q10: number | null;
  q90: number | null;
  errorBase: number | null;
  errorHeight: number;
  forecastBase: number | null;
  forecastHeight: number;
  changePct: number | null;
};

interface Props {
  series?: PriceSeries | null;
  modelReadings?: Record<string, LongTermModelReading> | null;
  pricePathForecast?: PricePathForecast | null;
  loading?: boolean;
  error?: boolean;
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Realized history and forward forecast are deliberately rendered separately. */
export function PriceTrendChart({ series, modelReadings, pricePathForecast, loading = false, error = false }: Props) {
  const { l } = useI18n();
  const [periodKey, setPeriodKey] = useState<Period["key"]>("1m");
  const [yZoom, setYZoom] = useState(1);
  const [chartHeight, setChartHeight] = useState(320);
  const [forecastChartHeight, setForecastChartHeight] = useState(280);
  const resizeStart = useRef<{ y: number; height: number } | null>(null);
  const forecastResizeStart = useRef<{ y: number; height: number } | null>(null);
  const period = PERIODS.find((item) => item.key === periodKey) ?? PERIODS[0];

  const points = useMemo<TrendPoint[]>(() => {
    const source = [...(series?.points ?? [])]
      .filter((point) => finite(point.close) && point.close > 0)
      .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    const selected = source.slice(-period.days);
    const firstClose = selected[0]?.close ?? null;
    const selectedDates = new Set(selected.map((point) => point.timestamp.slice(0, 10)));

    const forecastByDate = new Map<string, { predicted: number | null; q10: number | null; q90: number | null }>();
    if (pricePathForecast?.status === "ok") {
      for (const item of [...(pricePathForecast.points ?? []), ...(pricePathForecast.historical_points ?? [])]) {
        if (!item?.date) continue;
        forecastByDate.set(item.date.slice(0, 10), {
          predicted: finite(item.predicted) ? item.predicted : null,
          q10: finite(item.q10) ? item.q10 : null,
          q90: finite(item.q90) ? item.q90 : null,
        });
      }
    }

    const rows: TrendPoint[] = selected.map((point) => {
      const date = point.timestamp.slice(0, 10);
      const path = forecastByDate.get(date);
      const modelClose = path?.predicted ?? null;
      const comparisonClose = modelClose;
      const error = comparisonClose != null ? Math.abs(point.close - comparisonClose) : 0;
      const q10 = path?.q10 ?? null;
      const q90 = path?.q90 ?? null;
      return {
        date,
        close: point.close,
        modelClose,
        q10,
        q90,
        errorBase: comparisonClose != null ? Math.min(point.close, comparisonClose) : null,
        errorHeight: error,
        forecastBase: q10 != null && q90 != null && q90 >= q10 ? q10 : null,
        forecastHeight: q10 != null && q90 != null && q90 >= q10 ? q90 - q10 : 0,
        changePct: firstClose ? ((point.close / firstClose) - 1) * 100 : 0,
      };
    });

    const lastActualDate = rows.at(-1)?.date;
    const future = lastActualDate
      ? [...forecastByDate.entries()]
        .filter(([date, value]) => date > lastActualDate && value.predicted != null)
        .sort(([left], [right]) => left.localeCompare(right))
      : [];
    for (const [date, path] of future) {
      const q10 = path.q10;
      const q90 = path.q90;
      rows.push({
        date,
        close: null,
        modelClose: path.predicted,
        q10,
        q90,
        errorBase: null,
        errorHeight: 0,
        forecastBase: q10 != null && q90 != null && q90 >= q10 ? q10 : null,
        forecastHeight: q10 != null && q90 != null && q90 >= q10 ? q90 - q10 : 0,
        changePct: null,
      });
    }

    // Keep long-horizon reference points when no daily path is available.
    const last = [...rows].reverse().find((point) => point.close != null);
    if (!future.length && last && modelReadings && (period.key === "1y" || period.key === "3y")) {
      const forecastPoints = ([
        ["excess_return_120d", 120],
        ["excess_return_240d", 240],
      ] as const).flatMap(([task, days]) => {
        const reading = modelReadings[task];
        if (!reading || !finite(reading.q50)) return [];
        const date = new Date(`${last.date}T00:00:00Z`);
        date.setUTCDate(date.getUTCDate() + days);
        return [{
          date: date.toISOString().slice(0, 10), close: null,
          modelClose: Math.max(0.01, last.close! * (1 + reading.q50)),
          q10: null, q90: null, errorBase: null, errorHeight: 0,
          forecastBase: null, forecastHeight: 0, changePct: null,
        } satisfies TrendPoint];
      });
      rows.push(...forecastPoints);
    }
    return rows;
  }, [modelReadings, period.days, period.key, pricePathForecast, series]);

  const latest = [...points].reverse().find((point) => point.close != null);
  const first = points.find((point) => point.close != null);
  const change = first && latest ? latest.changePct : null;
  const actualPoints = points.filter((point) => point.close != null);
  const futurePoints = points.filter((point) => point.close == null && point.modelClose != null);
  const forecastAnchor = latest ? { ...latest, q10: latest.q10 ?? latest.close, q90: latest.q90 ?? latest.close } : null;
  const forecastPoints = forecastAnchor ? [forecastAnchor, ...futurePoints] : futurePoints;
  const errorRows = actualPoints.filter((point) => point.errorHeight > 0);
  const overlapMae = errorRows.length ? errorRows.reduce((total, point) => total + (point.errorHeight / (point.close || 1)) * 100, 0) / errorRows.length : null;
  const displayedMae = overlapMae ?? pricePathForecast?.mean_abs_error_pct ?? null;
  const hasReplayPrediction = actualPoints.some((point) => point.modelClose != null);
  const hasFutureForecast = futurePoints.length > 0;
  const hasErrorArea = errorRows.length > 0;
  const hasForecastBand = forecastPoints.some((point) => point.forecastHeight > 0);
  const forecastStart = futurePoints[0]?.date ?? null;

  const yDomain = useMemo<[number, number] | ["auto", "auto"]>(() => {
    const values = actualPoints.flatMap((point) => [point.close, point.modelClose]).filter(finite);
    if (!values.length) return ["auto", "auto"];
    const rawMin = Math.min(...values); const rawMax = Math.max(...values);
    const rawSpan = Math.max(rawMax - rawMin, Math.max(Math.abs(rawMax), 1) * 0.01);
    const padding = Math.max(rawSpan * 0.12, 0.5); const center = (rawMin + rawMax) / 2;
    const halfSpan = (rawSpan + padding * 2) / (2 * yZoom);
    return [center - halfSpan, center + halfSpan];
  }, [actualPoints, yZoom]);
  const forecastYDomain = useMemo<[number, number] | ["auto", "auto"]>(() => {
    const values = forecastPoints.flatMap((point) => [point.modelClose, point.q10, point.q90]).filter(finite);
    if (!values.length) return ["auto", "auto"];
    const rawMin = Math.min(...values); const rawMax = Math.max(...values);
    const rawSpan = Math.max(rawMax - rawMin, Math.max(Math.abs(rawMax), 1) * 0.01);
    const padding = Math.max(rawSpan * 0.12, 0.5); const center = (rawMin + rawMax) / 2;
    const halfSpan = (rawSpan + padding * 2) / (2 * yZoom);
    return [center - halfSpan, center + halfSpan];
  }, [forecastPoints, yZoom]);

  const beginResize = (event: React.PointerEvent<HTMLButtonElement>) => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); resizeStart.current = { y: event.clientY, height: chartHeight }; };
  const resizeChart = (event: React.PointerEvent<HTMLButtonElement>) => { if (!resizeStart.current) return; setChartHeight(Math.min(640, Math.max(240, resizeStart.current.height + event.clientY - resizeStart.current.y))); };
  const endResize = () => { resizeStart.current = null; };
  const beginForecastResize = (event: React.PointerEvent<HTMLButtonElement>) => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); forecastResizeStart.current = { y: event.clientY, height: forecastChartHeight }; };
  const resizeForecastChart = (event: React.PointerEvent<HTMLButtonElement>) => { if (!forecastResizeStart.current) return; setForecastChartHeight(Math.min(560, Math.max(220, forecastResizeStart.current.height + event.clientY - forecastResizeStart.current.y))); };
  const endForecastResize = () => { forecastResizeStart.current = null; };
  const formatTooltip = (value: unknown, name: unknown): [string, string] => {
    const labels: Record<string, string> = { close: l("实际收盘", "Actual close"), modelClose: l("历史回放预测", "Historical replay prediction"), q10: l("预测下沿", "Forecast lower band"), q90: l("预测上沿", "Forecast upper band") };
    const key = String(name);
    return [Number(value).toFixed(2), labels[key] ?? key];
  };
  const controls = <div className="stock-workspace__chart-controls">
    <div className="stock-workspace__period-tabs" role="tablist" aria-label={l("价格走势周期", "Price trend period")}>
      {PERIODS.map((item) => <button key={item.key} type="button" role="tab" aria-selected={item.key === periodKey} className={item.key === periodKey ? "stock-workspace__period-tab is-active" : "stock-workspace__period-tab"} onClick={() => setPeriodKey(item.key)}>{l(item.zh, item.en)}</button>)}
    </div>
        <div className="stock-workspace__y-zoom" aria-label={l("纵轴局部缩放", "Y-axis zoom")}><span>{l("纵轴", "Y")}</span><button type="button" aria-label={l("缩小纵轴", "Zoom out y-axis")} disabled={yZoom <= 1} onClick={() => setYZoom((value) => Math.max(1, Number((value - 0.5).toFixed(2))))}>−</button><strong>×{yZoom.toFixed(2)}</strong><button type="button" aria-label={l("放大纵轴", "Zoom in y-axis")} disabled={yZoom >= 4} onClick={() => setYZoom((value) => Math.min(4, Number((value + 0.5).toFixed(2))))}>＋</button><button type="button" className="stock-workspace__y-zoom-reset" disabled={yZoom === 1} onClick={() => setYZoom(1)}>{l("恢复", "Reset")}</button></div>
  </div>;

  return <div className="stock-workspace__trend-stack">
    <Panel eyebrow={l("历史价格", "Historical price")} title={l(`最近${period.zh.replace("近", "")}实际收盘与历史预测`, `${period.en} actual close and historical predictions`)} actions={controls}>
      {loading ? <p className="stock-workspace__empty">{l("正在读取价格曲线…", "Loading the price trend…")}</p> : null}
      {!loading && error ? <p className="stock-workspace__empty">{l("价格曲线暂时无法读取，请稍后重试。", "The price trend is temporarily unavailable. Try again later.")}</p> : null}
      {!loading && !error && !actualPoints.length ? <p className="stock-workspace__empty">{l("暂无本地实际行情序列。", "No local realized price series is available.")}</p> : null}
      {!loading && !error && actualPoints.length ? <>
        <div className="stock-workspace__trend-meta"><span>{l("最新收盘", "Latest close")} <strong>{latest?.close != null ? latest.close.toFixed(2) : "—"}</strong></span><span className={change != null && change < 0 ? "is-negative" : "is-positive"}>{l("区间变化", "Period change")} <strong>{change != null ? `${change >= 0 ? "+" : ""}${change.toFixed(2)}%` : "—"}</strong></span>{displayedMae != null ? <span>{l(overlapMae != null ? "历史重叠平均误差" : "历史平均误差", overlapMae != null ? "Historical overlap MAE" : "Historical MAE")} <strong>{displayedMae.toFixed(2)}%</strong></span> : null}</div>
        <div key={`history-chart-${periodKey}-${yZoom}`} className="chart-frame stock-workspace__trend-chart" style={{ height: `${chartHeight}px` }} aria-label={l("实际收盘与历史回放预测折线图", "Actual close and historical replay prediction line chart")}><ResponsiveContainer width="100%" height="100%"><ComposedChart data={actualPoints} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="date" minTickGap={28} /><YAxis domain={yDomain} allowDataOverflow width={64} tickFormatter={(value) => Number(value).toFixed(0)} /><Tooltip formatter={formatTooltip} />{hasErrorArea ? <><Area dataKey="errorBase" stackId="error-gap" stroke="none" fill="transparent" isAnimationActive={false} /><Area dataKey="errorHeight" stackId="error-gap" stroke="none" fill="rgba(224,138,54,0.22)" isAnimationActive={false} /></> : null}<Line type="monotone" dataKey="close" name="close" stroke="#2864dc" dot={false} strokeWidth={2.5} connectNulls={false} />{hasReplayPrediction ? <Line type="monotone" dataKey="modelClose" name="modelClose" stroke="#e08a36" dot={{ r: 2 }} strokeWidth={1.8} connectNulls /> : null}</ComposedChart></ResponsiveContainer></div>
        <button type="button" className="stock-workspace__trend-resizer" aria-label={l("上下拖动调整图表高度", "Drag up or down to resize the chart")} title={l("上下拖动调整图表高度", "Drag up or down to resize the chart")} onPointerDown={beginResize} onPointerMove={resizeChart} onPointerUp={endResize} onPointerCancel={endResize} onLostPointerCapture={endResize} />
        <div className="stock-workspace__trend-legend" aria-label={l("历史价格走势图例", "Historical price chart legend")}><span><i className="stock-workspace__trend-legend-swatch is-actual" />{l("实际收盘", "Actual close")}</span>{hasReplayPrediction ? <span><i className="stock-workspace__trend-legend-swatch is-history-model" />{l("历史回放预测", "Historical replay prediction")}</span> : null}{hasErrorArea ? <span><i className="stock-workspace__trend-legend-swatch is-error" />{l("橙色阴影为历史误差", "Orange shading is historical error")}</span> : null}</div>
        <p className="stock-workspace__trend-note">{l("这张图只看已经发生的价格：蓝线是实际收盘，橙线是模型在当时信息下的历史回放预测，橙色阴影表示两者之间的误差。", "This chart only shows realized prices: blue is the actual close, orange is the model replay prediction, and orange shading shows their gap.")}</p>
      </> : null}
    </Panel>

    <Panel eyebrow={l("未来价格预测", "Forward price forecast")} title={l("未来20日模型路径与可能范围", "Forward 20-session model path and possible range")} actions={<div className="stock-workspace__trend-meta stock-workspace__trend-meta--compact">{pricePathForecast?.horizon_days ? <span>{l("预测窗口", "Horizon")} <strong>{pricePathForecast.horizon_days}{l("日", "d")}</strong></span> : null}{pricePathForecast?.mean_abs_error_pct != null ? <span>{l("历史平均误差", "Historical average error")} <strong>{pricePathForecast.mean_abs_error_pct.toFixed(2)}%</strong></span> : null}</div>}>
      {!loading && !error && !hasFutureForecast ? <p className="stock-workspace__empty">{l("暂无未来模型预测路径。", "No forward model forecast is available.")}</p> : null}
      {!loading && !error && hasFutureForecast ? <>
        <div key={`forecast-chart-${yZoom}`} className="chart-frame stock-workspace__trend-chart" style={{ height: `${forecastChartHeight}px` }} aria-label={l("未来模型预测折线图", "Forward model forecast line chart")}><ResponsiveContainer width="100%" height="100%"><ComposedChart data={forecastPoints} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="date" minTickGap={28} /><YAxis domain={forecastYDomain} allowDataOverflow width={64} tickFormatter={(value) => Number(value).toFixed(0)} /><Tooltip formatter={formatTooltip} />{hasForecastBand ? <><Area dataKey="forecastBase" stackId="forecast-band" stroke="none" fill="transparent" isAnimationActive={false} /><Area dataKey="forecastHeight" stackId="forecast-band" stroke="none" fill="rgba(155,107,206,0.16)" isAnimationActive={false} /></> : null}{forecastStart ? <ReferenceLine x={forecastStart} stroke="#9b6bce" strokeDasharray="3 3" label={{ value: l("预测开始", "Forecast"), position: "insideTopRight", fill: "#7952a5", fontSize: 11 }} /> : null}{hasForecastBand ? <><Line type="monotone" dataKey="q10" name="q10" stroke="rgba(155,107,206,0.62)" dot={false} strokeWidth={1.2} strokeDasharray="4 4" connectNulls /><Line type="monotone" dataKey="q90" name="q90" stroke="rgba(155,107,206,0.62)" dot={false} strokeWidth={1.2} strokeDasharray="4 4" connectNulls /></> : null}<Line type="monotone" dataKey="modelClose" name="modelClose" stroke="#9b6bce" dot={{ r: 2 }} strokeWidth={2.6} connectNulls /></ComposedChart></ResponsiveContainer></div>
        <button type="button" className="stock-workspace__trend-resizer" aria-label={l("上下拖动调整预测图高度", "Drag up or down to resize the forecast chart")} title={l("上下拖动调整预测图高度", "Drag up or down to resize the forecast chart")} onPointerDown={beginForecastResize} onPointerMove={resizeForecastChart} onPointerUp={endForecastResize} onPointerCancel={endForecastResize} onLostPointerCapture={endForecastResize} />
        <div className="stock-workspace__trend-legend" aria-label={l("未来预测图例", "Forward forecast legend")}><span><i className="stock-workspace__trend-legend-swatch is-model" />{l("逐日主预测路径", "Daily central path")}</span>{hasForecastBand ? <span><i className="stock-workspace__trend-legend-swatch is-band" />{l("可能波动范围", "Possible range")}</span> : null}</div>
        <p className="stock-workspace__trend-note">{l("紫线根据截至当前的历史行情与成交信息，一次推演未来20个交易日的逐日路径；浅紫色区域表示模型的不确定范围，不代表实际走势或保证结果。", "The purple line is a direct 20-session daily path inferred from historical price and turnover information available today. The light-purple area expresses uncertainty, not a guaranteed result.")}</p>
      </> : null}
    </Panel>
  </div>;
}
