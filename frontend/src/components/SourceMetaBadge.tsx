import React from "react";
import type { SourceMeta } from "./types";
import { formatDateTime } from "./utils";

interface SourceMetaBadgeProps {
  meta?: SourceMeta | null;
  label?: string;
  compact?: boolean;
}

export default function SourceMetaBadge({ meta, label = "来源", compact = false }: SourceMetaBadgeProps) {
  if (!meta) {
    return <span className="source-meta-badge missing">{label}: 缺失</span>;
  }

  const tone = meta.synthetic_ratio >= 0.8 ? "synthetic" : meta.overrides.length ? "override" : "real";
  const suffix = compact
    ? `${meta.mode} · ${meta.provider}`
    : `${meta.mode} · ${meta.provider} · as_of ${formatDateTime(meta.as_of)} · synthetic ${(meta.synthetic_ratio * 100).toFixed(0)}%`;

  return (
    <span className={`source-meta-badge ${tone}`} title={`overrides: ${meta.overrides.join(", ") || "none"}`}>
      {label}: {suffix}
    </span>
  );
}
