import React from "react";
import { ClipboardList, History, RefreshCcw, Scale } from "lucide-react";
import AuditPanel from "../../../components/AuditPanel";
import ChecklistPanel from "../../../components/ChecklistPanel";
import ConditionAlignmentPanel from "../../../components/ConditionAlignmentPanel";
import DebatePanel from "../../../components/DebatePanel";
import RefreshReviewPanel from "../../../components/RefreshReviewPanel";
import RevisionLoopPanel from "../../../components/RevisionLoopPanel";
import SourceMetaBadge from "../../../components/SourceMetaBadge";
import VersionPanel from "../../../components/VersionPanel";
import type { RefreshReviewPayload, ResearchPayload } from "../../../components/types";
import { evidenceLabels, formatDateTime } from "../../../components/utils";

interface AuditStepProps {
  research: ResearchPayload;
  refreshReview: RefreshReviewPayload | null;
  token: string | null;
  onRefreshDaily: () => void;
}

export default function AuditStep({ research, refreshReview, token, onRefreshDaily }: AuditStepProps) {
  return (
    <div className="step-content">
      <section className="panel research-panel wide">
        <div className="panel-head">
          <div>
            <h2>LLM Judge 研究质量审稿 Agent</h2>
            <p>审稿对象是研究过程是否严谨，不评价这只股票是否值得买。</p>
          </div>
          <span className="risk-badge medium">质量 {research.evidenceAudit.score}</span>
        </div>
        <SourceMetaBadge meta={research.run?.sourceMeta ?? research.sourceMeta} />
        <AuditPanel research={research} />
        <RevisionLoopPanel research={research} />
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>条件对齐</h2>
            <p>{research.conditionAlignment.summary}</p>
          </div>
        </div>
        <ConditionAlignmentPanel research={research} />
      </section>

      <section className="panel research-panel wide">
        <div className="panel-head">
          <div>
            <h2>Bull / Bear Debate Agent</h2>
            <p>把结论拆成支持观点、反方观点、中立裁判和推翻条件。</p>
          </div>
          <span className="pill"><Scale size={15} />{research.debate.judge.stance}</span>
        </div>
        <DebatePanel research={research} />
      </section>

      <section className="main-grid">
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>报告版本复盘</h2>
              <p>{research.reportVersions.delta.summary}</p>
            </div>
            <button className="ghost-button" onClick={onRefreshDaily} type="button">
              <RefreshCcw size={16} />刷新证据
            </button>
          </div>
          <VersionPanel research={research} token={token} />
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>投资观察清单</h2>
              <p>报告的终点不是结论，而是下一步要盯住什么。</p>
            </div>
            <span className="pill"><ClipboardList size={15} />{research.observationChecklist.length} 项</span>
          </div>
          <ChecklistPanel research={research} />
        </section>
      </section>

      <section className="panel wide">
        <div className="panel-head">
          <div>
            <h2>证据刷新与结论变化</h2>
            <p>刷新后展示证据变化、claim 状态变化和风险评分变化原因。</p>
          </div>
          <span className="pill"><History size={15} />{refreshReview ? refreshReview.count : 0} 标的</span>
        </div>
        <RefreshReviewPanel review={refreshReview} />
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>经验历史池</h2>
            <p>过期信息不删除，用于复盘 Agent 判断质量。</p>
          </div>
          <span className="pill"><RefreshCcw size={15} />归档</span>
        </div>
        <div className="history-list">
          {research.experienceHistory.length ? (
            research.experienceHistory.map((record) => (
              <article className="history-item" key={record.id}>
                <strong>{evidenceLabels[record.source_type as keyof typeof evidenceLabels] ?? record.source_type}</strong>
                <p>{record.archived_claim}</p>
                <small>{formatDateTime(record.archived_at)} · {record.reason}</small>
              </article>
            ))
          ) : (
            <p className="empty-text">当前没有已归档证据。演示时可缩短有效期触发归档。</p>
          )}
        </div>
      </section>
    </div>
  );
}
