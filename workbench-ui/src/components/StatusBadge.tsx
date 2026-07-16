const STATUS_LABELS: Record<string, string> = {
  complete: "已完成",
  passed: "通过",
  research_only: "研究级",
  partial: "部分可用",
  degraded: "已降级",
  unavailable: "不可用",
  abstain: "暂不判断",
  blocked: "已阻断",
  fresh: "新鲜",
  stale_usable: "可用旧数据",
  expired: "已过期",
  unsupported: "未覆盖",
  confirmed_none: "已确认无事件",
  events_present: "有事件",
  fetch_failed: "抓取失败"
};

function statusClass(status: string) {
  return status.toLowerCase().replace(/[^a-z0-9_]+/g, "-");
}

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return (
    <span className={`status-badge status-badge--${statusClass(status)}`} role="status">
      <span className="status-badge__dot" aria-hidden="true" />
      {label ?? STATUS_LABELS[status] ?? status}
    </span>
  );
}
