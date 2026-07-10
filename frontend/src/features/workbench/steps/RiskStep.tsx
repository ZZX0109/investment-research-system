import React from "react";
import { BarChart3, Upload } from "lucide-react";
import DocumentAnalysisPanel from "../../../components/DocumentAnalysisPanel";
import MLRiskPanel from "../../../components/MLRiskPanel";
import RadarBars from "../../../components/RadarBars";
import SourceMetaBadge from "../../../components/SourceMetaBadge";
import TokenCompressionPanel from "../../../components/TokenCompressionPanel";
import type { ResearchPayload } from "../../../components/types";

interface RiskStepProps {
  research: ResearchPayload;
  uploadState: string;
  onDocumentUpload: (file: File | null) => void;
  onReportFrequencyChange: (frequency: string) => void;
}

export default function RiskStep({ research, uploadState, onDocumentUpload, onReportFrequencyChange }: RiskStepProps) {
  return (
    <div className="step-content">
      <section className="panel research-panel wide">
        <div className="panel-head">
          <div>
            <h2>时序模型风险分布</h2>
            <p>CNN/Transformer/表格基线共同服务历史情景检索和样本外风险校准。</p>
          </div>
          <span className={`status-badge ${research.mlRiskSummary?.modelStatus === "valid" ? "fresh" : research.mlRiskSummary?.modelStatus === "stale" ? "inferred" : "expired"}`}>
            {research.mlRiskSummary?.modelStatus ?? "missing"}
          </span>
        </div>
        <SourceMetaBadge meta={research.mlRiskSummary?.sourceMeta} />
        <MLRiskPanel research={research} />
      </section>

      <section className="panel research-panel wide">
        <div className="panel-head">
          <div>
            <h2>Agent Token Compression Report</h2>
            <p>量化原始行情/证据/文档输入与结构化摘要输入的 token 差异和一致性。</p>
          </div>
          <span className="pill">
            <BarChart3 size={15} />
            {research.tokenCompressionReport?.tokenReductionPercent ?? 0}%
          </span>
        </div>
        <SourceMetaBadge meta={research.tokenCompressionReport?.sourceMeta} />
        <TokenCompressionPanel research={research} />
      </section>

      <section className="panel wide">
        <div className="panel-head">
          <div>
            <h2>财报多模态解析 Agent</h2>
            <p>上传财报或研报后，系统会拆分文本、表格和图表，表格指标进入结构化库。</p>
          </div>
          <label className="upload-button">
            <Upload size={16} /> 上传文件
            <input type="file" accept=".pdf,.txt,.md,.csv" onChange={(event) => onDocumentUpload(event.target.files?.[0] ?? null)} />
          </label>
        </div>
        <p className="upload-state">{uploadState}</p>
        <DocumentAnalysisPanel research={research} />
      </section>

      <section className="main-grid">
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>偏好权重系统</h2>
              <p>偏好会改变指标权重、风险阈值和报告排序。</p>
            </div>
          </div>
          <RadarBars items={research.preferenceWeights.map((item) => ({ label: item.factor, value: item.weight }))} />
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>报告频率</h2>
              <p>{research.reportSettings.description}</p>
            </div>
          </div>
          <div className="frequency-grid">
            {[["daily", "每日"], ["weekly", "每周"], ["monthly", "每月"], ["trigger_only", "触发时"]].map(([key, label]) => (
              <button className={research.reportSettings.frequency === key ? "selected" : ""} key={key} onClick={() => onReportFrequencyChange(key)}>
                {label}
              </button>
            ))}
          </div>
        </section>
      </section>
    </div>
  );
}
