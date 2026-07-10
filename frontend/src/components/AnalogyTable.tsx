import React from "react";
import type { HistoricalAnalogy } from "./types";
import { percent, metricClass } from "./utils";

interface AnalogyTableProps {
  analogies: HistoricalAnalogy[];
}

export default function AnalogyTable({ analogies }: AnalogyTableProps) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>情景日期</th>
            <th>相似模式</th>
            <th>相似度</th>
            <th>后续 1 周</th>
            <th>后续 1 月</th>
            <th>后续 3 月</th>
            <th>最大回撤</th>
          </tr>
        </thead>
        <tbody>
          {analogies.map((item) => (
            <tr key={`${item.asOfDate}-${item.pattern}`}>
              <td>{item.asOfDate}</td>
              <td>{item.pattern}<small className="table-note">{item.note}</small></td>
              <td>{Math.round(item.similarity * 100)}%</td>
              <td className={metricClass(item.return1w)}>{percent(item.return1w)}</td>
              <td className={metricClass(item.return1m)}>{percent(item.return1m)}</td>
              <td className={metricClass(item.return3m)}>{percent(item.return3m)}</td>
              <td className="negative">{percent(item.maxDrawdown)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
