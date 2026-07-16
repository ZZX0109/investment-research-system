import { StatusBadge } from "./StatusBadge";

export function ShadowProgress({ sessionCount, validCount, abstainCount, completed, forwardStatus, primaryStatus }: {
  sessionCount: number;
  validCount: number;
  abstainCount: number;
  completed: Record<string, number>;
  forwardStatus: string;
  primaryStatus: string;
}) {
  return (
    <div className="shadow-progress">
      <div className="shadow-progress__header"><strong>研究 Shadow 前向验证</strong><StatusBadge status={validCount > 0 ? "partial" : "abstain"} /></div>
      <div className="shadow-progress__metrics">
        <span><b>{sessionCount}</b><small>已冻结</small></span>
        <span><b>{validCount}</b><small>有效</small></span>
        <span><b>{abstainCount}</b><small>暂不判断</small></span>
      </div>
      <div className="shadow-progress__milestones">
        {[1, 5, 20, 60].map((horizon) => <span key={horizon}><b>{completed[String(horizon)] ?? 0}</b><small>T+{horizon}</small></span>)}
      </div>
      <p className="muted">20 日报告：{forwardStatus} · 60 日主模型复核：{primaryStatus} · 尚未达到正式验证门槛</p>
    </div>
  );
}
