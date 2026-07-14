import type { Provenance } from "../api/types";

export function SourceBadge({ provenance }: { provenance: Provenance }) {
  return (
    <span className={`source-badge source-badge--${provenance.source_type}`}>
      {provenance.data_mode} / {provenance.source_type}
    </span>
  );
}
