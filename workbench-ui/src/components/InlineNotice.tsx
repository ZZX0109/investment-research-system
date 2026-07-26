type InlineNoticeTone = "info" | "warn" | "block";

import { useI18n } from "../i18n";

export function InlineNotice({
  title,
  body,
  tone = "info"
}: {
  title: string;
  body: string;
  tone?: InlineNoticeTone;
}) {
  const { l } = useI18n();
  const label = tone === "block"
    ? l("阻断", "Blocked")
    : tone === "warn"
      ? l("注意", "Notice")
      : l("提示", "Info");
  return (
    <article className={`story-card story-card--${tone}`}>
      <div className="story-card__header">
        <strong>{title}</strong>
        <span className="tag">{label}</span>
      </div>
      <p>{body}</p>
    </article>
  );
}
