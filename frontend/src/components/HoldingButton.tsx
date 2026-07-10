import React from "react";
import { ChevronRight } from "lucide-react";
import type { Holding } from "./types";
import { percent, metricClass, formatDateTime } from "./utils";

interface HoldingButtonProps {
  holding: Holding;
  selected: boolean;
  onClick: () => void;
}

export default function HoldingButton({ holding, selected, onClick }: HoldingButtonProps) {
  return (
    <button className={`holding-row ${selected ? "selected" : ""}`} onClick={onClick}>
      <span>
        <strong>{holding.symbol}</strong>
        <small>{holding.name} · {holding.market === "us" ? "美股/ETF" : "A股/基金"}</small>
        <small>{holding.dataSource ?? "local cache"} · {holding.observedAt ? formatDateTime(holding.observedAt) : "未刷新"}</small>
      </span>
      <span>{holding.weight.toFixed(1)}%</span>
      <span className={metricClass(holding.dayChange)}>{percent(holding.dayChange)}</span>
      <ChevronRight size={18} />
    </button>
  );
}
