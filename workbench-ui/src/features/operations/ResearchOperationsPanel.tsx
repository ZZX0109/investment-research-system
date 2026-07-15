import { CalendarClock, FileUp } from "lucide-react";
import { useState } from "react";
import { Panel } from "../../components/Panel";
import type { ReportSchedule } from "../../api/types";
import {
  useCreateReportScheduleMutation,
  useReportSchedulesQuery,
  useUploadDocumentMutation
} from "../../hooks/useWorkbenchQueries";
import { useWorkbenchStore } from "../../state/workbenchStore";

export function ResearchOperationsPanel() {
  const assetId = useWorkbenchStore((state) => state.selectedAssetId);
  const mode = useWorkbenchStore((state) => state.mode);
  const [frequency, setFrequency] = useState<ReportSchedule["frequency"]>("weekly");
  const schedules = useReportSchedulesQuery();
  const createSchedule = useCreateReportScheduleMutation();
  const upload = useUploadDocumentMutation();

  return (
    <Panel eyebrow="Operations" title="Documents & Inspection">
      <div className="control-grid">
        <label><span>Inspection frequency</span>
          <select value={frequency} onChange={(event) => setFrequency(event.target.value as ReportSchedule["frequency"])}>
            <option value="manual">Manual</option><option value="daily">Daily</option><option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option><option value="event_triggered">Event triggered</option>
          </select>
        </label>
        <button className="icon-button" type="button" disabled={!(["research", "real"].includes(mode)) || !assetId || createSchedule.isPending} onClick={() => createSchedule.mutate({ asset_id: assetId, frequency, enabled: frequency !== "manual", timezone: "Asia/Shanghai" })}>
          <CalendarClock size={16} aria-hidden="true" /><span>Set</span>
        </button>
      </div>
      <label className="file-control">
        <span><FileUp size={16} aria-hidden="true" /> Financial PDF</span>
        <input type="file" accept="application/pdf" disabled={!(["research", "real"].includes(mode))} onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) upload.mutate({ file, assetId });
        }} />
      </label>
      {upload.data ? <p className="muted">{upload.data.filename}: {upload.data.parse_status}, {upload.data.page_count} pages, {upload.data.tables.length} tables.</p> : null}
      <div className="schedule-list">
        {(schedules.data ?? []).slice(0, 4).map((item) => (
          <div className="schedule-row" key={item.id}>
            <span>{item.frequency.replace("_", " ")}</span>
            <span className="tag">{item.next_run_at ? new Date(item.next_run_at).toLocaleDateString() : "manual"}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
