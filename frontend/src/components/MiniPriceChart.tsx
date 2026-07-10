import React from "react";
import { makePath } from "./utils";

interface MiniPriceChartProps {
  points: number[];
}

export default function MiniPriceChart({ points }: MiniPriceChartProps) {
  const width = 420;
  const height = 180;
  const path = makePath(points.length ? points : [1, 1], width, height);
  return (
    <svg className="mini-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="价格路径">
      {[0, 1, 2].map((line) => (
        <line className="grid-line" key={line} x1="0" x2={width} y1={(height / 3) * line + 10} y2={(height / 3) * line + 10} />
      ))}
      <path className="line-path" d={path} />
    </svg>
  );
}
