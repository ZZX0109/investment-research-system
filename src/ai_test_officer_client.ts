import { spawn } from "node:child_process";
import path from "node:path";

export type AiTestOfficerGateStatus = "pass" | "fail" | "blocked" | "needs-human-review";

export interface AiTestOfficerClientOptions {
  baseUrl?: string;
  token?: string;
  bearerToken?: string;
  timeoutMs?: number;
}

export class AiTestOfficerClient {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly bearerToken?: string;
  private readonly timeoutMs: number;
  constructor(options: AiTestOfficerClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? process.env.AI_TEST_OFFICER_URL ?? "http://127.0.0.1:4317").replace(/\/$/, "");
    this.token = options.token ?? process.env.AI_TEST_OFFICER_TOKEN ?? "dev-local-token";
    this.bearerToken = options.bearerToken ?? process.env.AI_TEST_OFFICER_BEARER_TOKEN;
    this.timeoutMs = options.timeoutMs ?? 30_000;
  }

  private async request<T>(route: string, init?: RequestInit): Promise<T> {
    if (process.env.NODE_ENV === "production" && !this.bearerToken) {
      throw new Error("AI_TEST_OFFICER_BEARER_TOKEN is required in production; shared agent tokens are disabled");
    }
    const response = await fetch(`${this.baseUrl}${route}`, {
      ...init,
      signal: AbortSignal.timeout(this.timeoutMs),
      headers: { "content-type": "application/json", ...(this.bearerToken ? { authorization: `Bearer ${this.bearerToken}` } : { "x-agent-token": this.token }), ...(init?.headers ?? {}) }
    });
    if (!response.ok) throw new Error(`ai_test_officer_http_${response.status}`);
    return response.json() as Promise<T>;
  }

  createRun(input: { runId?: string; organizationId?: string; projectId?: string; actor: string; idempotencyKey: string; input: Record<string, unknown> }) {
    return this.request<{ run: Record<string, unknown> }>("/v1/runs", { method: "POST", body: JSON.stringify(input) });
  }

  getRun(runId: string) { return this.request<{ run: Record<string, unknown> }>(`/v1/runs/${encodeURIComponent(runId)}`); }
  getEvents(runId: string) { return this.request<{ events: Array<Record<string, unknown>> }>(`/v1/runs/${encodeURIComponent(runId)}/events`); }
  getArtifacts(runId: string) { return this.request<{ artifacts: Array<Record<string, unknown>> }>(`/v1/runs/${encodeURIComponent(runId)}/artifacts`); }
  getReport(runId: string) { return this.request<{ report: Record<string, unknown> }>(`/v1/runs/${encodeURIComponent(runId)}/report`); }

  control(runId: string, action: "plan-approval" | "permissions" | "pause" | "resume" | "cancel" | "decision-override", input: { expectedVersion: number; actor: string; idempotencyKey: string; payload?: Record<string, unknown> }) {
    return this.request<{ run: Record<string, unknown> }>(`/v1/runs/${encodeURIComponent(runId)}/${action}`, { method: "POST", body: JSON.stringify(input) });
  }

  async executeRun(input: { organizationId: string; projectId?: string; actor: string; input: Record<string, unknown> }) {
    const key = crypto.randomUUID();
    let run = (await this.createRun({ organizationId: input.organizationId, projectId: input.projectId, actor: input.actor, idempotencyKey: key, input: input.input })).run as { id: string; state: string; version: number };
    run = (await this.control(run.id, "plan-approval", { expectedVersion: run.version, actor: input.actor, idempotencyKey: `${key}:plan` })).run as typeof run;
    run = (await this.control(run.id, "permissions", { expectedVersion: run.version, actor: input.actor, idempotencyKey: `${key}:permission` })).run as typeof run;
    const terminal = new Set(["completed", "failed", "blocked", "cancelled", "awaiting-human-review"]);
    while (!terminal.has(run.state)) {
      await new Promise((resolve) => setTimeout(resolve, 750));
      run = (await this.getRun(run.id)).run as typeof run;
    }
    return { run, ...(await this.getReport(run.id)) };
  }
}

export async function runOfficialAiTestOfficerCli(input: {
  workspaceRoot?: string;
  command?: "commit-check" | "commit-check:strict" | "requirement-acceptance" | "patrol" | "demo:verify";
  env?: Record<string, string>;
}) {
  const workspaceRoot = path.resolve(input.workspaceRoot ?? process.env.AI_TEST_OFFICER_WORKSPACE ?? path.join(process.cwd(), "ai-test-officer"));
  const command = input.command ?? "commit-check";
  return new Promise<number>((resolve, reject) => {
    const child = spawn("npm", ["--prefix", workspaceRoot, "run", command], {
      cwd: workspaceRoot,
      shell: false,
      stdio: "inherit",
      env: { ...process.env, ...input.env }
    });
    child.once("error", reject);
    child.once("exit", (code) => resolve(code ?? 4));
  });
}
