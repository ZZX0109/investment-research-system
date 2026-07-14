export function splitList(value: string) {
  return value
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export function splitCommandArgs(value: string) {
  return value
    .split(/\s+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export function formatAuditSignalSummary(signals?: Record<string, unknown>) {
  if (!signals) {
    return [];
  }
  const changedFiles = readStringList(signals.changedFiles);
  const consoleErrorSummaries = readStringList(signals.consoleErrorSummaries);
  const networkErrorSummaries = readStringList(signals.networkErrorSummaries);
  const runtimeSignals = Array.isArray(signals.runtimeSignals)
    ? signals.runtimeSignals.filter(isRecord)
    : [];
  const retrySignals = isRecord(signals.retrySignals) ? signals.retrySignals : undefined;
  return [
    changedFiles.length > 0 ? `changed files: ${changedFiles.slice(0, 3).join(", ")}` : undefined,
    consoleErrorSummaries.length > 0 ? `console: ${consoleErrorSummaries[0]}` : undefined,
    networkErrorSummaries.length > 0 ? `network: ${networkErrorSummaries[0]}` : undefined,
    runtimeSignals.length > 0
      ? `runtime: ${runtimeSignals
          .slice(0, 2)
          .map((signal) => `${String(signal.phase ?? "phase")} ${String(signal.status ?? "unknown")}`)
          .join(", ")}`
      : undefined,
    retrySignals?.attemptCount ? `retry attempts: ${String(retrySignals.attemptCount)}` : undefined
  ].filter((entry): entry is string => Boolean(entry));
}

export function formatAuditArtifactSignalSummary(
  artifacts: Array<{ kind: string; metadata: Record<string, unknown> }>
) {
  return artifacts
    .flatMap((artifact) => {
      const firstError = readMetadataString(artifact.metadata.firstError) ??
        readFirstFailureLine(artifact.metadata.inlinePreview);
      const firstFailure = readMetadataString(artifact.metadata.firstFailure) ??
        readFirstFailureLine(artifact.metadata.inlinePreview);
      return [
        artifact.kind === "console-log" && firstError ? `console: ${firstError}` : undefined,
        artifact.kind === "network-log" && firstFailure ? `network: ${firstFailure}` : undefined
      ];
    })
    .filter((entry): entry is string => Boolean(entry))
    .slice(0, 3);
}

function readMetadataString(value: unknown) {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function readFirstFailureLine(value: unknown) {
  if (typeof value !== "string") {
    return undefined;
  }
  return value
    .split(/\r?\n/)
    .map((entry) => entry.trim())
    .find((entry) => /\b(error|failed|exception|uncaught|5\d\d|4\d\d|net::err)\b/i.test(entry));
}

function readStringList(value: unknown) {
  return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string") : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
