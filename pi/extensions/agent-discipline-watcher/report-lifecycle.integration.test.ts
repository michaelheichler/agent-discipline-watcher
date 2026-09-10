import { expect, test } from "bun:test";
import { resolve } from "node:path";
import { createExtension } from "./index";
import type { WatcherResult } from "./watcher";

type Handler = (event: unknown, ctx?: unknown) => Promise<unknown>;

const CONTEXT = {
  cwd: process.cwd(),
  sessionManager: { getSessionId: () => "host-report-session" },
};
const REPORT_CALL = {
  toolName: "write",
  toolCallId: "report-1",
  input: { path: "xd://report_issue", content: "write: report route was rejected" },
};
const REPORT_RESULT = { ...REPORT_CALL, content: [{ type: "text", text: "Noted, thanks!" }] };

function createHarness(run: (event: string, payload: Record<string, unknown>) => WatcherResult = () => ({})) {
  const handlers = new Map<string, Handler>();
  const calls: string[] = [];
  const pi = {
    on(name: string, handler: Handler) { handlers.set(name, handler); },
    registerCommand() {},
    async sendMessage() {},
  };
  const checkedRun = (event: string, payload: Record<string, unknown>) => {
    calls.push(event);
    return run(event, payload);
  };
  createExtension(pi as never, checkedRun as never, undefined as never, async (_ctx, payload) => checkedRun("JudgeReview", payload));
  return { handlers, calls };
}

test("leaves native report handling to OMP without a filesystem scan", async () => {
  const { handlers, calls } = createHarness();
  expect(await handlers.get("tool_call")!(REPORT_CALL, CONTEXT)).toBeUndefined();
  expect(await handlers.get("tool_result")!(REPORT_RESULT, CONTEXT)).toBeUndefined();
  expect(await handlers.get("session_stop")!({}, CONTEXT)).toBeUndefined();
  expect(calls).toEqual(["Stop"]);
});

test("lets a literal JavaScript wrapper dispatch the native report", async () => {
  const { handlers, calls } = createHarness();
  const wrapper = {
    toolName: "eval",
    toolCallId: "wrapper-1",
    input: { language: "js", code: "display(await tool.write({path:'xd://report_issue',content:'write: rejected report route'}));" },
  };
  expect(await handlers.get("tool_call")!(wrapper, CONTEXT)).toBeUndefined();
  expect(await handlers.get("tool_call")!(REPORT_CALL, CONTEXT)).toBeUndefined();
  expect(await handlers.get("tool_result")!(REPORT_RESULT, CONTEXT)).toBeUndefined();
  expect(await handlers.get("tool_result")!({ ...wrapper, content: REPORT_RESULT.content }, CONTEXT)).toBeUndefined();
  expect(await handlers.get("session_stop")!({}, CONTEXT)).toBeUndefined();
  expect(calls).toEqual(["Stop"]);
});

test.each([
  { path: "xd://report_issue", content: { report: "invalid" } },
  { path: "xd://report_issue" },
  { file_path: "xd://report_issue", content: "write: rejected" },
  { path: "xd://report_issue", file_path: "ordinary.md", content: "write: rejected" },
  { path: "xd://report_issue", filePath: "xd://report_issue", content: "write: rejected" },
  { path: "xd://report_issue/", content: "write: rejected" },
  { path: "xd://report_issue?next=write", content: "write: rejected" },
  { path: "xd://report_issue#next", content: "write: rejected" },
  { path: "XD://report_issue", content: "write: rejected" },
  { path: " xd://report_issue", content: "write: rejected" },
  { path: "xd://write", content: "{}" },
])("blocks malformed or other virtual write targets: %j", async input => {
  const { handlers, calls } = createHarness();
  expect(await handlers.get("tool_call")!({ ...REPORT_CALL, input }, CONTEXT)).toMatchObject({ block: true });
  expect(calls).toEqual([]);
});

test.each(["Write", "edit", "mcp__files__write"])("keeps %s outside the native report exception", async toolName => {
  const { handlers } = createHarness();
  expect(await handlers.get("tool_call")!({ ...REPORT_CALL, toolName }, CONTEXT)).toMatchObject({ block: true });
});

test("ordinary file writes still reach the discipline gate", async () => {
  const { handlers, calls } = createHarness(event => event === "PreToolUse" ? { decision: "block", reason: "file finding" } : {});
  const file = { ...REPORT_CALL, input: { path: "ordinary.md", content: "file content" } };
  expect(await handlers.get("tool_call")!(file, CONTEXT)).toEqual({ block: true, reason: "file finding" });
  expect(calls).toEqual(["PreToolUse"]);
});

test("a failed report does not latch unresolved file verification", async () => {
  const { handlers, calls } = createHarness();
  expect(await handlers.get("tool_call")!(REPORT_CALL, CONTEXT)).toBeUndefined();
  expect(await handlers.get("tool_result")!({ ...REPORT_RESULT, isError: true }, CONTEXT)).toBeUndefined();
  expect(await handlers.get("session_stop")!({}, CONTEXT)).toBeUndefined();
  expect(calls).toEqual(["Stop"]);
});

test("a report result cannot hide an accepted filesystem write", async () => {
  const scanned: string[] = [];
  const { handlers, calls } = createHarness((event, payload) => {
    if (event === "PostToolUse") scanned.push(String((payload.tool_input as { file_path: string }).file_path));
    return {};
  });
  const target = resolve(import.meta.dir, "watcher.ts");
  const file = { ...REPORT_CALL, input: { path: target, content: "updated" } };
  expect(await handlers.get("tool_call")!(file, CONTEXT)).toBeUndefined();
  await handlers.get("tool_result")!(REPORT_RESULT, CONTEXT);
  expect(await handlers.get("session_stop")!({}, CONTEXT)).toBeUndefined();
  expect(scanned).toEqual([target]);
  expect(calls).toEqual(["PreToolUse", "PostToolUse", "JudgeReview", "Stop"]);
});
