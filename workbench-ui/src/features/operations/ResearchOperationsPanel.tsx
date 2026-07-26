import { CalendarClock, FileUp } from "lucide-react";
import { useState } from "react";
import { Panel } from "../../components/Panel";
import type { ReportSchedule } from "../../api/types";
import {
  useCreateReportScheduleMutation,
  useReportSchedulesQuery,
  useUploadDocumentMutation
} from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";

export function ResearchOperationsPanel() {
  const { formatDateTime, l, term } = useI18n();
  const assetId = useWorkbenchStore((state) => state.selectedAssetId);
  const mode = useWorkbenchStore((state) => state.mode);
  const [frequency, setFrequency] = useState<ReportSchedule["frequency"]>("weekly");
  const schedules = useReportSchedulesQuery();
  const createSchedule = useCreateReportScheduleMutation();
  const upload = useUploadDocumentMutation();

  return (
    <Panel eyebrow={l("研究操作", "Operations")} title={l("文档与定期检查", "Documents & Inspection")}>
      <div className="control-grid">
        <label><span>{l("检查频率", "Inspection frequency")}</span>
          <select value={frequency} onChange={(event) => setFrequency(event.target.value as ReportSchedule["frequency"])}>
            <option value="manual">{l("手动", "Manual")}</option><option value="daily">{l("每日", "Daily")}</option><option value="weekly">{l("每周", "Weekly")}</option>
            <option value="monthly">{l("每月", "Monthly")}</option><option value="event_triggered">{l("事件触发", "Event triggered")}</option>
          </select>
        </label>
        <button className="icon-button" type="button" disabled={!(["research", "real"].includes(mode)) || !assetId || createSchedule.isPending} onClick={() => createSchedule.mutate({ asset_id: assetId, frequency, enabled: frequency !== "manual", timezone: "Asia/Shanghai" })}>
          <CalendarClock size={16} aria-hidden="true" /><span>{l("设置", "Set")}</span>
        </button>
      </div>
      <label className="file-control">
        <span><FileUp size={16} aria-hidden="true" /> {l("财务 PDF", "Financial PDF")}</span>
        <input type="file" accept="application/pdf" disabled={!(["research", "real"].includes(mode))} onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) upload.mutate({ file, assetId });
        }} />
      </label>
      {upload.data ? <p className="muted">{upload.data.filename}：{term(upload.data.parse_status)}，{upload.data.page_count} {l("页", "pages")}，{upload.data.tables.length} {l("张表格", "tables")}。</p> : null}
      <div className="schedule-list">
        {(schedules.data ?? []).slice(0, 4).map((item) => (
          <div className="schedule-row" key={item.id}>
            <span>{term(item.frequency)}</span>
            <span className="tag">{item.next_run_at ? formatDateTime(item.next_run_at) : l("手动", "manual")}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
