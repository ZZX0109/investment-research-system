import { useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Panel } from "../../components/Panel";
import { useI18n } from "../../i18n";

export interface PricePathPoint {
  date: string; // YYYY-MM-DD
  actual?: number | null; // realized close (history) — null in the future
  predicted?: number | null; // p50 path forecast (present + future)
  q10?: number | null; // 10th-percentile path
  q90?: number | null; // 90th-percentile path
}

export interface TemporalModelStatus {
  vendored_source: boolean;
  torch: boolean;
  trained_weights: boolean;
  ready: boolean;
  blocking: string[];
}

export interface PricePathForecast {
  status: "ok" | "unavailable";
  model?: string | null;
  horizon_days?: number | null;
  mean_abs_error_pct?: number | null; // mean |actual - predicted| / actual over the realized window
  generated_at?: string | null;
  points: PricePathPoint[];
  // §1 row-5 (训练说清楚): the kittenCN temporal prereq state when the path
  // degrades to the quantile projection.
  temporal_model_status?: TemporalModelStatus | null;
}

interface Props {
  pricePathForecast?: PricePathForecast | null;
  loading?: boolean;
  error?: boolean;
}

/**
 * Predicted-vs-actual price-path chart (kittenCN reference, §1 step 6).
 *
 * Plots the realized close (actual) against the model's p50 path forecast,
 * wrapped in a q10–q90 band, so the user can SEE how the forecast tracked
 * reality — the predicted-vs-actual error is no longer hidden ("训练说清楚"
 * for the path model, mirroring the accuracy-surface work for the long-term
 * model). The band is rendered with a stacked-area trick (transparent q10
 * base + a filled (q90−q10) area on top) so it is theme-independent.
 *
 * When no path model is trained (status !== "ok" or no points) the chart
 * degrades to an honest empty state rather than fabricating a path.
 */
export function PricePathChart({ pricePathForecast, loading = false, error = false }: Props) {
  const { l } = useI18n();

  const rows = useMemo(() => {
    const points = pricePathForecast?.points ?? [];
    return points
      .filter((p) => p && p.date)
      .map((p) => {
        const q10 = Number.isFinite(p.q10 as number) ? (p.q10 as number) : null;
        const q90 = Number.isFinite(p.q90 as number) ? (p.q90 as number) : null;
        return {
          date: p.date,
          actual: Number.isFinite(p.actual as number) ? (p.actual as number) : null,
          predicted: Number.isFinite(p.predicted as number) ? (p.predicted as number) : null,
          q10,
          q90,
          // Stacked-area band: a transparent q10 base + a filled (q90−q10) area
          // draws exactly the q10→q90 region, independent of the theme bg.
          bandHeight: q10 != null && q90 != null && q90 >= q10 ? q90 - q10 : 0,
        };
      })
      .sort((a, b) => a.date.localeCompare(b.date));
  }, [pricePathForecast]);

  const hasData = !loading && !error && rows.length > 0 && pricePathForecast?.status === "ok";
  const mae = pricePathForecast?.mean_abs_error_pct ?? null;

  return (
    <Panel
      eyebrow={l("价格路径", "Price path")}
      title={l("预测 vs 实际价格路径", "Predicted vs actual price path")}
      actions={
        <>
          {hasData && pricePathForecast?.model ? (
            <span className="stock-workspace__trend-meta">
              {l("模型", "Model")} <strong>{pricePathForecast.model}</strong>
              {pricePathForecast.horizon_days
                ? ` · ${l("窗口", "horizon")} ${pricePathForecast.horizon_days}${l("日", "d")}`
                : null}
            </span>
          ) : null}
          {/* §1 row-5 (训练说清楚): surface the kittenCN temporal prereq state
              when the temporal model is not ready — the honest degrade reason,
              never a silent fallback to the quantile fan. */}
          {(() => {
            const tms = pricePathForecast?.temporal_model_status;
            if (!tms || tms.ready) return null;
            const parts: string[] = [];
            if (tms.vendored_source) parts.push(l("源已备", "src"));
            if (tms.torch) parts.push(l("torch就绪", "torch"));
            if (!tms.trained_weights) parts.push(l("训练待权重", "weights"));
            return (
              <span className="stock-workspace__trend-meta">
                {l("时序模型", "Temporal")} {parts.join(" · ")}
              </span>
            );
          })()}
        </>
      }
    >
      {loading ? (
        <p className="stock-workspace__empty">{l("正在读取价格路径…", "Loading the price path…")}</p>
      ) : null}
      {!loading && error ? (
        <p className="stock-workspace__empty">
          {l("价格路径暂时无法读取，请稍后重试。", "The price path is temporarily unavailable. Try again later.")}
        </p>
      ) : null}
      {!loading && !error && !hasData ? (
        <p className="stock-workspace__empty">
          {l(
            "价格路径模型尚未训练（kittenCN 价格路径移植后填充）。长期超额收益 / 回撤模型精度见验证指标卡。",
            "No price-path model is trained yet (populated once the kittenCN price-path port lands). Long-term excess-return / drawdown accuracy is on the validation-metrics card.",
          )}
        </p>
      ) : null}
      {hasData ? (
        <div className="chart-frame stock-workspace__trend-chart" aria-label={l("预测vs实际价格路径图", "Predicted vs actual price path chart")}>
          {mae != null ? (
            <div className="stock-workspace__trend-meta">
              <span>
                {l("平均绝对误差", "Mean abs error")}{" "}
                <strong>{mae.toFixed(2)}%</strong>
              </span>
            </div>
          ) : null}
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(127,127,127,0.18)" />
              <XAxis dataKey="date" minTickGap={28} />
              <YAxis domain={["auto", "auto"]} width={64} tickFormatter={(value) => Number(value).toFixed(0)} />
              <Tooltip
                formatter={(value, name) => {
                  const labels: Record<string, [string, string]> = {
                    actual: [l("实际", "Actual"), "actual"],
                    predicted: [l("预测", "Predicted"), "predicted"],
                    q10: [l("10分位", "q10"), "q10"],
                    q90: [l("90分位", "q90"), "q90"],
                  };
                  const key = String(name ?? "");
                  const numericValue = Number(value);
                  const label = labels[key] ? labels[key][0] : key;
                  const point = rows.find((r) => String((r as Record<string, unknown>)[key]) === String(value));
                  const actual = point?.actual;
                  const predicted = point?.predicted;
                  let suffix = "";
                  if (key === "predicted" && actual != null && predicted != null) {
                    const gap = predicted - actual;
                    suffix = ` (Δ ${gap >= 0 ? "+" : ""}${gap.toFixed(2)})`;
                  }
                  return [Number.isFinite(numericValue) ? numericValue.toFixed(2) : "n/a", label + suffix];
                }}
              />
              {/* q10–q90 band: transparent base + filled (q90−q10) area. */}
              <Area dataKey="q10" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} />
              <Area dataKey="bandHeight" stackId="band" stroke="none" fill="rgba(120,150,220,0.18)" isAnimationActive={false} />
              <Line type="monotone" dataKey="q10" name="q10" stroke="rgba(120,150,220,0.55)" dot={false} strokeWidth={1.2} strokeDasharray="4 4" connectNulls />
              <Line type="monotone" dataKey="q90" name="q90" stroke="rgba(120,150,220,0.55)" dot={false} strokeWidth={1.2} strokeDasharray="4 4" connectNulls />
              <Line type="monotone" dataKey="predicted" name="predicted" stroke="#9b6bce" dot={false} strokeWidth={2.5} strokeDasharray="6 5" connectNulls />
              <Line type="monotone" dataKey="actual" name="actual" stroke="#2864dc" dot={false} strokeWidth={2.5} connectNulls={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : null}
    </Panel>
  );
}
