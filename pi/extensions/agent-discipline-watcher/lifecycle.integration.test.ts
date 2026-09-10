import { expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { createExtension } from "./index";
import { type WatcherResult } from "./watcher";

type Handler = (event: unknown, ctx?: unknown) => Promise<unknown>;

function createHarness(run: (event: string, payload: Record<string, unknown>) => WatcherResult) {
  const handlers = new Map<string, Handler>();
  const pi = {
    on(eventName: string, handler: Handler) {
      handlers.set(eventName, handler);
    },
    registerCommand() {},
    async sendMessage() {},
  };
  createExtension(
    pi as never,
    run as never,
    undefined as never,
    async (_ctx, payload) => run("JudgeReview", payload),
  );
  return handlers;
}

const TEST_CWD = process.cwd();
const FIXTURE_A = resolve(import.meta.dir, "lifecycle.ts");
const FIXTURE_B = resolve(import.meta.dir, "tool-adapter.ts");
const ctx = {
  cwd: TEST_CWD,
  sessionManager: { getSessionId: () => "lifecycle-session" },
};

test("re-verifies a failed target and releases Stop after the repaired scan passes", async () => {
  const events: string[] = [];
  let postScans = 0;
  const handlers = createHarness((event) => {
    events.push(event);
    if (event === "PostToolUse") {
      postScans += 1;
      if (postScans === 1) return { decision: "block", reason: "retry scan" };
    }
    return {};
  });
  await handlers.get("tool_result")!(
    { toolName: "write", input: { path: "a.md", content: "saved" }, content: [{ type: "text", text: "saved" }] },
    ctx,
  );
  await handlers.get("tool_result")!(
    { toolName: "write", input: { path: "a.md", content: "repaired" }, content: [{ type: "text", text: "saved" }] },
    ctx,
  );

  expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
  expect(events).toEqual(["PostToolUse", "PostToolUse", "JudgeReview", "Stop"]);
});

test("does not clear a failed target when another target scans successfully", async () => {
  const events: string[] = [];
  const handlers = createHarness((event, payload) => {
    events.push(`${event}:${JSON.stringify(payload.tool_input ?? {})}`);
    const filePath = (payload.tool_input as { file_path?: string } | undefined)?.file_path;
    if (event === "PostToolUse" && filePath?.endsWith("/a.md")) {
      return { decision: "block", reason: "a is still unverified" };
    }
    return {};
  });
  await handlers.get("tool_result")!(
    { toolName: "write", input: { path: "a.md", content: "saved" }, content: [{ type: "text", text: "saved" }] },
    ctx,
  );
  await handlers.get("tool_result")!(
    { toolName: "write", input: { path: "b.md", content: "saved" }, content: [{ type: "text", text: "saved" }] },
    ctx,
  );

  expect(await handlers.get("session_stop")!({}, ctx)).toEqual({
    decision: "block",
    reason: "agent-discipline-watcher could not verify every mutating tool result. Re-verify the touched file before stopping.",
  });
  expect(events.some(event => event.startsWith("Stop:"))).toBe(false);
});

test("uses the accepted pre-tool target when the result omits its path", async () => {
  const events: string[] = [];
  const handlers = createHarness((event, payload) => {
    events.push(`${event}:${JSON.stringify(payload.tool_input ?? {})}`);
    return {};
  });
  expect(await handlers.get("tool_call")!(
    { toolName: "write", toolCallId: "call-1", input: { path: "a.md", content: "saved" } },
    ctx,
  )).toBeUndefined();
  await handlers.get("tool_result")!(
    { toolName: "write", toolCallId: "call-1", input: {}, content: [{ type: "text", text: "saved" }] },
    ctx,
  );

  expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
  expect(events).toEqual([
    `PreToolUse:${JSON.stringify({ content: "saved", file_path: `${TEST_CWD}/a.md` })}`,
    `PostToolUse:${JSON.stringify({ file_path: `${TEST_CWD}/a.md` })}`,
    `JudgeReview:${JSON.stringify({ file_path: `${TEST_CWD}/a.md` })}`,
    "Stop:{}",
  ]);
});

test("blocks a target-required call before a pathless write can execute", async () => {
  const events: string[] = [];
  const handlers = createHarness(event => {
    events.push(event);
    return {};
  });
  const result = await handlers.get("tool_call")!(
    { toolName: "write", toolCallId: "missing-target", input: { content: "body" } },
    ctx,
  );

  expect(result).toMatchObject({ block: true });
  expect(events).toEqual([]);
});

test("keeps an orphan pathless result visible instead of silently releasing Stop", async () => {
  const handlers = createHarness(() => ({}));
  const result = await handlers.get("tool_result")!(
    {
      toolName: "write",
      toolCallId: "orphan-result",
      input: {},
      content: [{ type: "text", text: "saved" }],
    },
    ctx,
  );

  expect(result).toMatchObject({
    content: [{ text: expect.stringContaining("could not resolve") }],
  });
  expect(await handlers.get("session_stop")!({}, ctx)).toMatchObject({ decision: "block" });
});

test("does not retain a blocked pre-tool attempt when OMP reports its failure", async () => {
  const events: string[] = [];
  const handlers = createHarness(event => {
    events.push(event);
    return event === "PreToolUse" ? { decision: "block", reason: "denied" } : {};
  });
  expect(await handlers.get("tool_call")!(
    { toolName: "write", toolCallId: "call-denied", input: { path: "a.md", content: "body" } },
    ctx,
  )).toEqual({ block: true, reason: "denied" });
  await handlers.get("tool_result")!(
    { toolName: "write", toolCallId: "call-denied", input: {}, content: [{ type: "text", text: "denied" }], isError: true },
    ctx,
  );

  expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
  expect(events).toEqual(["PreToolUse", "PostToolUseFailure", "Stop"]);
});

test("does not latch an accepted tool result that reports an execution failure", async () => {
  const events: string[] = [];
  const handlers = createHarness(event => {
    events.push(event);
    return {};
  });
  expect(await handlers.get("tool_call")!(
    { toolName: "write", toolCallId: "call-failed", input: { path: "a.md", content: "body" } },
    ctx,
  )).toBeUndefined();
  await handlers.get("tool_result")!(
    {
      toolName: "write",
      toolCallId: "call-failed",
      input: {},
      content: [{ type: "text", text: "write failed before side effects" }],
      isError: true,
    },
    ctx,
  );

  expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
  expect(events).toEqual(["PreToolUse", "PostToolUseFailure", "Stop"]);
});

test("rechecks existing accepted targets after a partial multi-file failure", async () => {
  const events: string[] = [];
  const handlers = createHarness((event) => {
    events.push(event);
    return {};
  });
  const patch = `[${FIXTURE_A}#A1B2]\nPUT 1.=1:\n+ok\n[${FIXTURE_B}#C3D4]\nPUT 1.=1:\n+ok`;
  expect(await handlers.get("tool_call")!(
    { toolName: "edit", toolCallId: "partial-edit", input: { input: patch } },
    ctx,
  )).toBeUndefined();
  await handlers.get("tool_result")!(
    {
      toolName: "edit",
      toolCallId: "partial-edit",
      input: {},
      content: [{ type: "text", text: "one file was written before the edit failed" }],
      isError: true,
    },
    ctx,
  );

  expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
  expect(events).toEqual([
    "PreToolUse",
    "PreToolUse",
    "PostToolUseFailure",
    "PostToolUse",
    "JudgeReview",
    "PostToolUse",
    "JudgeReview",
    "Stop",
  ]);
});

test("releases a successful native delete without scanning the missing file", async () => {
  const root = mkdtempSync(resolve(tmpdir(), "adw-delete-"));
  const target = resolve(root, "obsolete.md");
  writeFileSync(target, "clean\n", "utf8");
  const events: string[] = [];
  try {
    const handlers = createHarness((event, payload) => {
      events.push(event);
      if (event === "PostToolUse") {
        const filePath = (payload.tool_input as { file_path?: unknown } | undefined)?.file_path;
        if (typeof filePath !== "string" || !existsSync(filePath)) return { decision: "block", reason: "missing file" };
      }
      return {};
    });
    expect(await handlers.get("tool_call")!(
      { toolName: "edit", toolCallId: "delete-file", input: { path: target, edits: [{ op: "delete" }] } },
      ctx,
    )).toBeUndefined();
    rmSync(target);
    await handlers.get("tool_result")!(
      { toolName: "edit", toolCallId: "delete-file", input: {}, content: [{ type: "text", text: "deleted" }] },
      ctx,
    );

    expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
    expect(events).toEqual(["PreToolUse", "Stop"]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("scans a declared delete target that still exists", async () => {
  const root = mkdtempSync(resolve(tmpdir(), "adw-delete-kept-"));
  const target = resolve(root, "still-present.md");
  writeFileSync(target, "clean\n", "utf8");
  const events: string[] = [];
  try {
    const handlers = createHarness(event => {
      events.push(event);
      return {};
    });
    expect(await handlers.get("tool_call")!(
      { toolName: "edit", toolCallId: "delete-kept", input: { path: target, edits: [{ op: "delete" }] } },
      ctx,
    )).toBeUndefined();
    await handlers.get("tool_result")!(
      { toolName: "edit", toolCallId: "delete-kept", input: {}, content: [{ type: "text", text: "deleted" }] },
      ctx,
    );

    expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
    expect(events).toEqual(["PreToolUse", "PostToolUse", "JudgeReview", "Stop"]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("pre-gates and leaves a read-only eval Python call without a post-write target", async () => {
  const payloads: Record<string, unknown>[] = [];
  const handlers = createHarness((event, payload) => {
    payloads.push({ event, ...payload });
    return {};
  });
  const input = { language: "py", code: "from pathlib import Path\nPath('a.md').read_text()" };
  expect(await handlers.get("tool_call")!(
    { toolName: "eval", toolCallId: "eval-read", input },
    ctx,
  )).toBeUndefined();
  await handlers.get("tool_result")!(
    { toolName: "eval", toolCallId: "eval-read", input, content: [{ type: "text", text: "body" }] },
    ctx,
  );
  await handlers.get("session_stop")!({}, ctx);

  expect(payloads.map(payload => payload.event)).toEqual(["PreToolUse", "Stop"]);
  expect(payloads[0]).toMatchObject({ tool_name: "Python", tool_input: { code: input.code } });
});

test("blocks an eval Python mutation through the shared pre-tool gate", async () => {
  const events: string[] = [];
  const handlers = createHarness((event, payload) => {
    events.push(event);
    if (event === "PreToolUse" && payload.tool_name === "Python") {
      return { decision: "block", reason: "Python mutations are denied by the shared gate" };
    }
    return {};
  });
  const input = { language: "py", code: "from pathlib import Path\nPath('a.md').write_text('body')" };
  expect(await handlers.get("tool_call")!(
    { toolName: "eval", toolCallId: "eval-write", input },
    ctx,
  )).toEqual({ block: true, reason: "Python mutations are denied by the shared gate" });
  await handlers.get("tool_result")!(
    {
      toolName: "eval",
      toolCallId: "eval-write",
      input,
      content: [{ type: "text", text: "blocked" }],
      isError: true,
    },
    ctx,
  );

  expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
  expect(events).toEqual(["PreToolUse", "PostToolUseFailure", "Stop"]);
});

test("pre-gates notebook aliases before allowing the edit", async () => {
  const events: string[] = [];
  const handlers = createHarness((event, payload) => {
    events.push(`${event}:${payload.tool_name ?? ""}`);
    if (event === "PreToolUse" && payload.tool_name !== "NotebookEdit") {
      return { decision: "block", reason: "notebook alias was not normalized" };
    }
    return {};
  });
  expect(await handlers.get("tool_call")!(
    {
      toolName: "notebook",
      toolCallId: "notebook-1",
      input: { notebookPath: "notes.ipynb", newSource: "print(1)" },
    },
    ctx,
  )).toBeUndefined();

  expect(events).toEqual(["PreToolUse:NotebookEdit"]);
});

test("returns a failed Python result when a user command would mutate a file", async () => {
  const events: string[] = [];
  const handlers = createHarness((event, payload) => {
    events.push(event);
    if (event === "PreToolUse" && payload.tool_name === "Python" && String((payload.tool_input as { code?: string }).code).includes("write_text")) {
      return { decision: "block", reason: "Python mutations are denied by the shared gate" };
    }
    return {};
  });
  const readResult = await handlers.get("user_python")!(
    { code: "from pathlib import Path\nPath('a.md').read_text()", cwd: TEST_CWD },
    ctx,
  );
  const writeResult = await handlers.get("user_python")!(
    { code: "from pathlib import Path\nPath('a.md').write_text('body')", cwd: TEST_CWD },
    ctx,
  );

  expect(readResult).toBeUndefined();
  expect((writeResult as { result: { exitCode: number; output: string } }).result).toMatchObject({
    exitCode: 1,
    output: expect.stringContaining("Python mutations are denied by the shared gate"),
  });
  expect(events).toEqual(["PreToolUse", "PreToolUse"]);
});
