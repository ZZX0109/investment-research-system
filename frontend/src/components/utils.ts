import type { EvidenceRecord } from "./types";

export const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0
});

export function percent(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function ratioPercent(value?: number) {
  return typeof value === "number" ? `${(value * 100).toFixed(2)}%` : "N/A";
}

export const evidenceLabels: Record<EvidenceRecord["sourceType"], string> = {
  market_data: "行情数据",
  financial_report: "财报数据",
  disclosure: "权威披露",
  news_event: "新闻事件",
  historical_analogy: "历史类比",
  model_inference: "模型推断"
};

export function metricClass(value: number) {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "";
}

export function passwordPolicyErrors(password: string) {
  const errors: string[] = [];
  if (password.length < 8) errors.push("至少 8 位");
  if (!/[a-z]/.test(password)) errors.push("缺少小写字母");
  if (!/[A-Z]/.test(password)) errors.push("缺少大写字母");
  if (!/\d/.test(password)) errors.push("缺少数字");
  if (!/[^a-zA-Z0-9]/.test(password)) errors.push("缺少特殊字符");
  return errors;
}

export function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function makePath(points: number[], width: number, height: number) {
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const scaleX = (index: number) => (index / Math.max(1, points.length - 1)) * width;
  const scaleY = (value: number) => height - ((value - min) / range) * (height - 34) - 16;
  return points.map((value, index) => `${index === 0 ? "M" : "L"} ${scaleX(index).toFixed(1)} ${scaleY(value).toFixed(1)}`).join(" ");
}
