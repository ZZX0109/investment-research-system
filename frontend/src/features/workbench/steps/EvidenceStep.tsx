import React from "react";
import { AlertTriangle, Database, Table2 } from "lucide-react";
import AnalogyTable from "../../../components/AnalogyTable";
import EvidenceGraphPanel from "../../../components/EvidenceGraphPanel";
import EvidenceTable from "../../../components/EvidenceTable";
import SourceMetaBadge from "../../../components/SourceMetaBadge";
import ToolCallPanel from "../../../components/ToolCallPanel";
import type { ResearchPayload } from "../../../components/types";

interface EvidenceStepProps {
  research: ResearchPayload;
}

export default function EvidenceStep({ research }: EvidenceStepProps) {
  return (
    <div className="step-content">
      <section className="panel research-panel wide">
        <div className="panel-head">
          <div>
            <h2>真实工具调用链</h2>
            <p>每个工具都记录输入、输出摘要、来源、时间、失败原因和关联 evidence id。</p>
          </div>
          <span className="pill"><Database size={15} />{research.toolCalls.length} 次调用</span>
        </div>
        <ToolCallPanel research={research} />
      </section>

      <section className="panel research-panel wide">
        <div className="panel-head">
          <div>
            <h2>证据链表格</h2>
            <p>每条信息记录来源、观察时间、有效期、置信度和是否为模型推断。</p>
          </div>
          <span className="pill"><Table2 size={15} />{research.evidence.length} 条</span>
        </div>
        <div className="source-meta-list">
          {research.evidence.slice(0, 4).map((item) => (
            <SourceMetaBadge key={item.id} meta={item.sourceMeta} label={item.sourceType} compact />
          ))}
        </div>
        <EvidenceTable records={research.evidence} />
        <EvidenceGraphPanel research={research} />
      </section>

      <section className="panel wide">
        <div className="panel-head">
          <div>
            <h2>过去三年相似情景</h2>
            <p>展示相似阶段后续 1 周 / 1 月 / 3 月风险分布，不输出涨跌预测。</p>
          </div>
          <span className="pill warn"><AlertTriangle size={15} />非预测</span>
        </div>
        <AnalogyTable analogies={research.historicalAnalogies} />
      </section>
    </div>
  );
}
