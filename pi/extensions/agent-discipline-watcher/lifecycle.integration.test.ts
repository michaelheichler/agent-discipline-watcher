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

test("scans an ordinary Bash write target resolved by the shared hook parser", async () => {
  const events: string[] = [];
  const scannedPaths: string[] = [];
  const handlers = createHarness((event, payload) => {
    events.push(event);
    if (event === "PostToolUse") scannedPaths.push(String((payload.tool_input as { file_path?: unknown }).file_path));
    return {};
  });
  const command = "printf body > lifecycle.ts";
  expect(await handlers.get("tool_call")!(
    { toolName: "bash", toolCallId: "bash-write", input: { command, cwd: import.meta.dir } },
    ctx,
  )).toBeUndefined();
  await handlers.get("tool_result")!(
    { toolName: "bash", toolCallId: "bash-write", input: {}, content: [{ type: "text", text: "written" }] },
    ctx,
  );

  expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
  expect(events).toEqual(["PreToolUse", "PostToolUse", "JudgeReview", "Stop"]);
  expect(scannedPaths).toEqual([FIXTURE_A]);
});

test("blocks a relative Bash target after a working-directory change", async () => {
  const events: string[] = [];
  const handlers = createHarness(event => {
    events.push(event);
    return {};
  });
  const result = await handlers.get("tool_call")!(
    { toolName: "bash", toolCallId: "bash-relative", input: { command: "cd sub && printf body > x.md" } },
    ctx,
  );

  expect(result).toMatchObject({ block: true });
  expect(events).toEqual([]);
});

test.each(["mcp__files__write", "mcp__fs__write_file"])("post-scans an admitted %s mutation", async toolName => {
  const events: string[] = [];
  const handlers = createHarness(event => {
    events.push(event);
    return {};
  });
  expect(await handlers.get("tool_call")!(
    {
      toolName,
      toolCallId: "mcp-write",
      input: toolName === "mcp__files__write" ? { path: FIXTURE_A, content: "updated" } : { path: FIXTURE_A },
    },
    ctx,
  )).toBeUndefined();
  await handlers.get("tool_result")!(
    { toolName, toolCallId: "mcp-write", input: {}, content: [{ type: "text", text: "written" }] },
    ctx,
  );

  expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
  expect(events).toEqual(["PreToolUse", "PostToolUse", "JudgeReview", "Stop"]);
});

test.each(["write", "mcp__fs__write_file"])("blocks %s before a pathless write can execute", async toolName => {
  const events: string[] = [];
  const handlers = createHarness(event => {
    events.push(event);
    return {};
  });
  const result = await handlers.get("tool_call")!(
    { toolName, toolCallId: "missing-target", input: { content: "body" } },
    ctx,
  );

  expect(result).toMatchObject({ block: true });
  expect(events).toEqual([]);
});

test("pre-gates native per-entry edits at each declared path", async () => {
  const preToolPaths: string[] = [];
  const handlers = createHarness((event, payload) => {
    if (event === "PreToolUse") preToolPaths.push(String((payload.tool_input as { file_path?: unknown }).file_path));
    return {};
  });
  expect(await handlers.get("tool_call")!(
    {
      toolName: "multiedit",
      toolCallId: "multi-entry",
      input: { edits: [{ path: FIXTURE_A, new_string: "a" }, { path: FIXTURE_B, new_string: "b" }] },
    },
    ctx,
  )).toBeUndefined();

  expect(preToolPaths).toEqual([FIXTURE_A, FIXTURE_B]);
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

test("honors a Stop permission denial from hook-specific output", async () => {
  const handlers = createHarness(event => event === "Stop"
    ? { hookSpecificOutput: { permissionDecision: "deny", permissionDecisionReason: "repair required" } }
    : {});

  expect(await handlers.get("session_stop")!({}, ctx)).toEqual({ decision: "block", reason: "repair required" });
});

test.each(["orphan", "evicted rejection"])("rechecks an existing path from an %s failed result", async status => {
  const events: string[] = [];
  const handlers = createHarness(event => {
    events.push(event);
    return event === "PreToolUse" ? { decision: "block", reason: "denied" } : {};
  });
  if (status === "evicted rejection") {
    for (let index = 0; index <= 1024; index += 1) {
      await handlers.get("tool_call")!(
        { toolName: "write", toolCallId: `denied-${index}`, input: { path: FIXTURE_A, content: "body" } }, ctx,
      );
    }
    events.length = 0;
  }
  await handlers.get("tool_result")!(
    { toolName: "write", toolCallId: "denied-0", input: { path: FIXTURE_A }, content: [{ type: "text", text: "failed" }], isError: true }, ctx,
  );

  expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
  expect(events).toEqual(["PostToolUseFailure", "PostToolUse", "JudgeReview", "Stop"]);
});

test("does not latch a failed result for a pre-denied call", async () => {
  const root = mkdtempSync(resolve(tmpdir(), "adw-denied-failure-"));
  const target = resolve(root, "denied.md");
  writeFileSync(target, "unchanged\n", "utf8");
  const events: string[] = [];
  try {
    const handlers = createHarness(event => {
      events.push(event);
      return event === "PreToolUse" ? { decision: "block", reason: "denied" } : {};
    });
    expect(await handlers.get("tool_call")!(
      { toolName: "write", toolCallId: "denied-failure", input: { path: target, content: "body" } },
      ctx,
    )).toEqual({ block: true, reason: "denied" });
    await handlers.get("tool_result")!(
      { toolName: "write", toolCallId: "denied-failure", input: { path: target }, content: [{ type: "text", text: "denied" }], isError: true },
      ctx,
    );

    expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
    expect(events).toEqual(["PreToolUse", "PostToolUseFailure", "Stop"]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("does not latch an accepted tool result that reports an execution failure", async () => {
  const root = mkdtempSync(resolve(tmpdir(), "adw-failed-"));
  const target = resolve(root, "not-created.md");
  const events: string[] = [];
  try {
    const handlers = createHarness(event => {
      events.push(event);
      return {};
    });
    expect(existsSync(target)).toBe(false);
    expect(await handlers.get("tool_call")!(
      { toolName: "write", toolCallId: "call-failed", input: { path: target, content: "body" } },
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
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
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

test.each(["edit", "mcp__fs__delete_file", "mcp__fs__remove_file"])("releases a successful %s delete without scanning the missing file", async toolName => {
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
      { toolName, toolCallId: "delete-file", input: toolName === "edit" ? { path: target, edits: [{ op: "delete" }] } : { path: target } },
      ctx,
    )).toBeUndefined();
    rmSync(target);
    await handlers.get("tool_result")!(
      { toolName, toolCallId: "delete-file", input: {}, content: [{ type: "text", text: "deleted" }] },
      ctx,
    );

    expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
    expect(events).toEqual(["PreToolUse", "Stop"]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test.each(["edit", "mcp__fs__delete_file"])("scans the %s delete target when it still exists", async toolName => {
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
      { toolName, toolCallId: "delete-kept", input: toolName === "edit" ? { path: target, edits: [{ op: "delete" }] } : { path: target } },
      ctx,
    )).toBeUndefined();
    await handlers.get("tool_result")!(
      { toolName, toolCallId: "delete-kept", input: {}, content: [{ type: "text", text: "deleted" }] },
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
