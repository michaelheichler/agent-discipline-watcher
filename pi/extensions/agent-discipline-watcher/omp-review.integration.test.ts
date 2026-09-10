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
  return {
    ctx, path,
    result: () => handlers.get("tool_result")!({ toolName: "write", input: { path }, content: [{ type: "text", text: "Saved" }] }, ctx),
    stop: () => handlers.get("session_stop")!({}, ctx),
  };
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
  expect(JSON.stringify(await harness.result())).toContain("every candidate exactly once");
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
    reason: expect.stringContaining("provider offline. Check the selected model and OMP login"),
  });
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
