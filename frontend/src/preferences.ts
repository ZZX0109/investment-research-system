import type { PreferenceKey } from "./components/types";

export const preferenceOptions: Array<{ key: PreferenceKey; label: string; description: string }> = [
  { key: "balanced", label: "均衡", description: "收益、风险、证据质量一起看" },
  { key: "conservative", label: "稳健", description: "回撤、集中度和波动优先" },
  { key: "growth", label: "成长", description: "营收增速和行业空间优先" },
  { key: "trading", label: "短线", description: "新闻、趋势和成交量优先" },
  { key: "fund", label: "基金", description: "行业暴露和风格漂移优先" },
];
