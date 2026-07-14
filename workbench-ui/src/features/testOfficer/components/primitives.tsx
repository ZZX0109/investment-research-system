import type { TestOfficerManifest } from "../../../api/types";
import { resolveArtifactPresentation } from "../model";

export function Metric({ label, value, tone = "neutral" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="metric-card">
      <div className="eyebrow">{label}</div>
      <div className={`metric-card__value metric-card__value--${tone}`}>{value}</div>
    </div>
  );
}

export function Detail({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <>
      <dt>{label}</dt>
      <dd className={mono ? "mono" : undefined}>{value}</dd>
    </>
  );
}

export function ArtifactPreview({
  artifact,
  onSelect,
  selected = false
}: {
  artifact: TestOfficerManifest["artifacts"][number];
  onSelect?: (artifactId: string) => void;
  selected?: boolean;
}) {
  const presentation = resolveArtifactPresentation(artifact);
  return (
    <div className="story-card">
      <div className="story-card__header">
        <strong>{artifact.kind}</strong>
        <span className="tag">{artifact.status}</span>
      </div>
      <p className="mono">{artifact.id}</p>
      {onSelect ? (
        <button
          className={`ghost-button ${selected ? "ghost-button--active" : ""}`}
          type="button"
          onClick={() => onSelect(artifact.id)}
        >
          {selected ? "focused artifact" : "focus artifact"}
        </button>
      ) : null}
      {presentation.imageSrc ? (
        <img className="test-officer-preview-image" src={presentation.imageSrc} alt={`${artifact.kind} preview`} />
      ) : null}
      {presentation.textPreview ? (
        <pre>{presentation.textPreview}</pre>
      ) : null}
      {presentation.downloadUrl ? (
        <a className="ghost-button" href={presentation.downloadUrl} rel="noreferrer" target="_blank">
          artifact
        </a>
      ) : null}
    </div>
  );
}
