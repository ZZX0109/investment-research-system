import React from "react";
import type { EvidenceRecord } from "./types";
import { evidenceLabels, formatDateTime } from "./utils";

interface EvidenceTableProps {
  records: EvidenceRecord[];
}

export default function EvidenceTable({ records }: EvidenceTableProps) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>类型</th>
            <th>结论/事实</th>
            <th>来源</th>
            <th>观察时间</th>
            <th>有效期</th>
            <th>置信度</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr key={record.id}>
              <td><span className={`source-chip ${record.sourceType}`}>{evidenceLabels[record.sourceType]}</span></td>
              <td>{record.claim}</td>
              <td>{record.sourceName}</td>
              <td>{formatDateTime(record.observedAt)}</td>
              <td>{formatDateTime(record.validUntil)}</td>
              <td>{Math.round(record.confidence * 100)}%</td>
              <td>{record.isExpired ? <span className="status-badge expired">已过期</span> : record.isModelInferred ? <span className="status-badge inferred">推断</span> : <span className="status-badge fresh">有效</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
