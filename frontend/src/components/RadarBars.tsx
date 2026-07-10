import React from "react";

interface RadarBarsProps {
  items: Array<{ label: string; value: number }>;
}

export default function RadarBars({ items }: RadarBarsProps) {
  return (
    <div className="exposure-list">
      {items.map((item) => (
        <div className="exposure-row" key={item.label}>
          <div className="exposure-label">
            <span>{item.label}</span>
            <strong>{item.value.toFixed(0)}</strong>
          </div>
          <div className="bar-track">
            <span style={{ width: `${Math.min(100, item.value)}%`, background: item.value > 70 ? "#e45f5f" : item.value > 45 ? "#f0a83a" : "#2dbb88" }} />
          </div>
        </div>
      ))}
    </div>
  );
}
