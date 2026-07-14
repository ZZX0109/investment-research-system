import { describe, expect, it } from "vitest";
import { ApiError } from "../workbench-ui/src/api/client";
import { formatQueryFailure, hasMissingSourceMetadata, isStaleAsOf } from "../workbench-ui/src/features/governance/runStatus";

describe("workbench run status helpers", () => {
  it("maps CSRF and session failures into user-facing recovery messages", () => {
    expect(formatQueryFailure(new ApiError(401, "Unauthorized"), "fallback")).toContain("sign in again");
    expect(formatQueryFailure(new ApiError(403, "Forbidden"), "fallback")).toContain("CSRF token");
    expect(formatQueryFailure(new ApiError(404, "Missing"), "fallback")).toContain("no longer available");
  });

  it("detects missing source metadata and stale run timestamps", () => {
    expect(hasMissingSourceMetadata({ mode: "real", provider: "", as_of: "2026-07-03T00:00:00.000Z" })).toBe(true);
    expect(
      isStaleAsOf(new Date(Date.now() - 9 * 24 * 60 * 60 * 1000).toISOString(), 7)
    ).toBe(true);
  });
});
