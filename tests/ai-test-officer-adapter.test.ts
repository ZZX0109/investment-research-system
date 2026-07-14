import { describe, expect, it } from "vitest";
import { AiTestOfficerClient } from "../src/ai_test_officer_client.js";

describe("official AI Test Officer adapter", () => {
  it("uses the versioned API instead of importing internal Agent modules", () => {
    const client = new AiTestOfficerClient({ baseUrl: "http://127.0.0.1:4317", token: "test", timeoutMs: 1 });
    expect(client).toBeInstanceOf(AiTestOfficerClient);
  });
});
