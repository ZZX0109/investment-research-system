import React from "react";
import { makePath } from "./utils";

interface LineChartSvgProps {
  points: number[];
}

export default function LineChartSvg({ points }: LineChartSvgProps) {
  const width = 720;
  const height = 250;
  const path = makePath(points, width, height);
  const fillPath = `${path} L ${width} ${height} L 0 ${height} Z`;
  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="组合收益曲线">
        <defs>
          <linearGradient id="lineFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#2dbb88" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#2dbb88" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {[0, 1, 2, 3].map((line) => (
          <line className="grid-line" key={line} x1="0" x2={width} y1={(height / 4) * line + 12} y2={(height / 4) * line + 12} />
        ))}
        <path d={fillPath} fill="url(#lineFill)" />
        <path className="line-path" d={path} />
      </svg>
    </div>
  );
}
