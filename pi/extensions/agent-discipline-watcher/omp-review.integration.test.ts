import { afterEach, expect, test } from "bun:test";
import type { Api, AssistantMessage, Model } from "@oh-my-pi/pi-ai";
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createExtension } from "./index";
import { createOmpReviewer, type OmpReviewContext } from "./omp-review";
import { type CompleteSimple } from "./omp-provider";

type Handler = (event: unknown, ctx: OmpReviewContext) => Promise<unknown>;
const directories: string[] = [];
const MODEL = { provider: "anthropic", id: "claude-haiku", api: "anthropic-messages" } as Model<Api>;
const COMMENT = "Returns the result because the caller needs a value.";

afterEach(() => {
  for (const directory of directories.splice(0)) rmSync(directory, { recursive: true, force: true });
});

function fixture(complete: CompleteSimple, enabled = true, timeoutMs = 30_000) {
  const cwd = realpathSync(mkdtempSync(join(tmpdir(), "adw-omp-native-")));
  directories.push(cwd);
  writeFileSync(join(cwd, ".agent-discipline.json"), JSON.stringify({
    data_boundary: { enabled }, adw_model: "anthropic/claude-haiku",
  }));
  const path = join(cwd, "source.py");
  writeFileSync(path, `# ${COMMENT}\n# ${COMMENT}\n`);
  const handlers = new Map<string, Handler>();
  const ctx = {
    cwd, model: MODEL,
    models: { list: () => [MODEL], current: () => MODEL, resolve: () => MODEL },
    modelRegistry: { getApiKey: async () => "session-key", resolver: () => "session-key" },
    sessionManager: { getSessionId: () => cwd },
  } as unknown as OmpReviewContext;
  const pi = { on: (name: string, handler: Handler) => handlers.set(name, handler), registerCommand() {}, sendMessage() {} };
  createExtension(pi as never, () => ({}), undefined, createOmpReviewer({ complete, timeoutMs }));
  const review = (target: string) =>
    handlers.get("tool_result")!({ toolName: "write", input: { path: target }, content: [{ type: "text", text: "Saved" }] }, ctx);
  return {
    ctx, path, review,
    result: () => review(path),
    stop: () => handlers.get("session_stop")!({}, ctx),
  };
}

function notes(items: Array<{ quote: string; problem: string; fix: string }>): AssistantMessage {
  return { content: [{ type: "text", text: JSON.stringify({ notes: items }) }], stopReason: "stop" } as AssistantMessage;
}

function answer(items: unknown[]): AssistantMessage {
  return { content: [{ type: "text", text: JSON.stringify({ items }) }], stopReason: "stop" } as AssistantMessage;
}

function verdict(index: number, narrates = false) {
  return { index, verdict: narrates ? "describes_code" : "states_why", reason: narrates ? "Describes the returned value." : "Names a constraint." };
}

test("native findings block Stop until the repaired source receives a clean review", async () => {
  let calls = 0;
  const harness = fixture(async () => answer([verdict(0), verdict(1, ++calls === 1)]));
  expect(JSON.stringify(await harness.result())).toContain(`${harness.path}:2:`);
  expect(await harness.stop()).toMatchObject({ decision: "block", reason: expect.stringContaining("Describes the returned value") });
  expect(calls).toBe(1);

  writeFileSync(harness.path, `# ${COMMENT}\n# Returns the token because callers need it.\n`);
  await harness.result();
  expect(await harness.stop()).toBeUndefined();
  expect(calls).toBe(2);
});

test("disabled review reads no model catalogue and makes no completion calls", async () => {
  let calls = 0;
  const harness = fixture(async () => { calls += 1; return answer([]); }, false);
  harness.ctx.models.list = () => { throw new Error("catalogue must remain unused"); };
  harness.ctx.models.resolve = () => { throw new Error("resolver must remain unused"); };
  await harness.result();
  expect(await harness.stop()).toBeUndefined();
  expect(calls).toBe(0);
});

test("omitted verdicts remain pending and a later complete review releases Stop", async () => {
  let calls = 0;
  const harness = fixture(async () => answer(++calls <= 2 ? [verdict(0)] : [verdict(0), verdict(1)]));
  expect(JSON.stringify(await harness.result())).toContain("received an unusable model response");
  expect(calls).toBe(2);
  expect(await harness.stop()).toBeUndefined();
  expect(calls).toBe(3);
});

test("timed out reviews name the failure and retry successfully during Stop recovery", async () => {
  let healthy = false;
  let calls = 0;
  const harness = fixture(async () => {
    calls += 1;
    return healthy ? answer([verdict(0), verdict(1)]) : new Promise(() => {});
  }, true, 10);
  expect(JSON.stringify(await harness.result())).toContain("timed out");
  expect(calls).toBe(2);
  healthy = true;
  expect(await harness.stop()).toBeUndefined();
  expect(calls).toBe(3);
});

test("all failed recovery attempts keep Stop blocked with an actionable reason", async () => {
  const harness = fixture(async () => { throw new Error("provider offline"); });
  await harness.result();
  expect(await harness.stop()).toMatchObject({
    decision: "block",
    reason: expect.stringContaining("the provider failed while reviewing the file. Check the selected model and OMP login"),
  });
});

test("does not expose provider error details in review guidance", async () => {
  const harness = fixture(async () => {
    throw new Error("Authorization: Bearer secret-value");
  });
  await harness.result();
  const stop = await harness.stop();
  expect(stop).toMatchObject({
    decision: "block",
    reason: expect.stringContaining("the provider failed while reviewing the file"),
  });
  expect(JSON.stringify(stop)).not.toContain("secret-value");
  expect(JSON.stringify(stop)).not.toContain("Authorization");
});

test("a policy change during review prevents retries from sending more source", async () => {
  let calls = 0;
  const harness = fixture(async () => {
    calls += 1;
    if (calls === 1) writeFileSync(join(harness.ctx.cwd, ".agent-discipline.json"), JSON.stringify({ data_boundary: { enabled: false } }));
    return answer(calls === 1 ? [verdict(0)] : [verdict(0), verdict(1, true)]);
  });
  await harness.result();
  expect(await harness.stop()).toBeUndefined();
  expect(calls).toBe(1);
  writeFileSync(join(harness.ctx.cwd, ".agent-discipline.json"), JSON.stringify({
    data_boundary: { enabled: true }, adw_model: "anthropic/claude-haiku",
  }));
  expect(JSON.stringify(await harness.result())).toContain("Describes the returned value");
  expect(calls).toBe(2);
});

test("source changed during review stays pending until the fresh source is judged", async () => {
  let calls = 0;
  const harness = fixture(async () => {
    if (++calls === 1) writeFileSync(harness.path, `# ${COMMENT}\n`);
    return answer(calls === 1 ? [verdict(0), verdict(1)] : [verdict(0)]);
  });
  expect(JSON.stringify(await harness.result())).toContain("source or policy changed");
  expect(calls).toBe(1);
  expect(await harness.stop()).toBeUndefined();
  expect(calls).toBe(2);
});

test("an ambiguous document quote drops only that note and names the cause without a retry", async () => {
  let calls = 0;
  const harness = fixture(async () => {
    calls += 1;
    return notes([
      { quote: "Repeated line.", problem: "Repeats itself.", fix: "Cut one copy." },
      { quote: "Unique closing sentence.", problem: "Vague ending.", fix: "Name the next step." },
    ]);
  });
  const document = join(harness.ctx.cwd, "guide.md");
  writeFileSync(document, "Repeated line.\nRepeated line.\nUnique closing sentence.\n");
  const text = JSON.stringify(await harness.review(document));
  expect(calls).toBe(1);
  expect(text).toContain("Vague ending.");
  expect(text).toContain("quote is ambiguous");
  expect(text).not.toContain("OMP review incomplete");
});

test("a multi-request review prepares once and re-prepares only before a retry", async () => {
  const operations: string[] = [];
  const request = (id: number) => ({ id, prompt: `request ${id}`, schema: {} });
  const bridge = (call: Record<string, unknown>) => {
    operations.push(String(call.operation));
    if (call.operation === "prepare") {
      return { enabled: true, model: "anthropic/claude-haiku", path: "a.py", digest: "d", requests: [request(0), request(1)] };
    }
    if (call.request_id === 1 && operations.filter(item => item === "validate").length === 2) throw new Error("try again");
    return {};
  };
  let calls = 0;
  const reviewer = createOmpReviewer({ bridge, complete: async () => { calls += 1; return answer([]); } });
  const { ctx } = fixture(async () => answer([]));
  expect(await reviewer(ctx, { tool_name: "Write" })).toEqual({});
  expect(calls).toBe(3);
  expect(operations).toEqual(["prepare", "validate", "validate", "prepare", "validate"]);
});

test("a rejected model output names the bridge cause instead of the login", async () => {
  const harness = fixture(async () => answer([verdict(0)]));
  const text = JSON.stringify(await harness.result());
  expect(text).toContain("review must answer every candidate exactly once");
  expect(text).not.toContain("OMP login");
});
