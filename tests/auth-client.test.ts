import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createWorkbenchClient } from "../workbench-ui/src/api/client";

function setDocumentCookie(cookie: string) {
  Object.defineProperty(globalThis, "document", {
    value: { cookie },
    configurable: true
  });
}

describe("auth api transport", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    Reflect.deleteProperty(globalThis, "document");
  });

  it("refreshes the session once and retries a protected request after a 401", async () => {
    setDocumentCookie("airc_csrf_token=test-csrf-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("Unauthorized", { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ user: { id: "1" } }), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "user-1",
            email: "investor@example.com",
            display_name: "Investor",
            auth_subject: "user:1",
            status: "active",
            version: { schema_version: "1.0.0", entity_version: 1 },
            provenance: {
              data_mode: "real",
              source_type: "manual_override",
              source_name: "auth-registration",
              observed_at: "2026-07-03T00:00:00Z",
              confidence: 1
            },
            created_at: "2026-07-03T00:00:00Z",
            updated_at: "2026-07-03T00:00:00Z"
          }),
          { status: 200 }
        )
      );
    vi.stubGlobal("fetch", fetchMock);

    const client = createWorkbenchClient("real");
    const session = await client.getSession();

    expect(session.user.email).toBe("investor@example.com");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/auth/refresh");
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: "POST",
      credentials: "include",
      headers: expect.objectContaining({ "x-csrf-token": "test-csrf-token" })
    });
    expect(fetchMock.mock.calls[2]?.[0]).toBe("/api/v1/auth/me");
  });

  it("does not attempt refresh for an explicit login failure", async () => {
    setDocumentCookie("airc_csrf_token=test-csrf-token");
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response("Invalid email or password", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = createWorkbenchClient("real");

    await expect(client.login({ email: "investor@example.com", password: "bad-password" })).rejects.toMatchObject({
      message: "Invalid email or password",
      kind: "auth"
    } satisfies Partial<ApiError>);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/auth/login");
  });

  it("keeps real mode on the API path instead of falling back to seeded assets", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response("backend down", { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);

    const client = createWorkbenchClient("real");

    await expect(client.getAssets()).rejects.toThrow("backend down");
    expect(client.dataSource).toBe("api");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/assets");
  });
});
