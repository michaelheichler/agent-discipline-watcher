import { expect, test } from "bun:test";
import { createExtension } from "./index";
import { resolve } from "node:path";
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

const FIXTURE = resolve(import.meta.dir, "lifecycle.ts");
const ctx = {
  cwd: process.cwd(),
  sessionManager: { getSessionId: () => "native-edit-session" },
};

test("accepts a native hashline edit inside the optional patch envelope", async () => {
  const events: string[] = [];
  const handlers = createHarness(event => {
    events.push(event);
    return {};
  });
  const input = `*** Begin Patch\n[${FIXTURE}#A1B2]\nPUT 1.=1:\n+updated\n*** End Patch`;
  expect(await handlers.get("tool_call")!(
    { toolName: "edit", toolCallId: "hashline-envelope", input: { input } },
    ctx,
  )).toBeUndefined();
  await handlers.get("tool_result")!(
    { toolName: "edit", toolCallId: "hashline-envelope", input: {}, content: [{ type: "text", text: "saved" }] },
    ctx,
  );

  expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
  expect(events).toEqual(["PreToolUse", "PostToolUse", "JudgeReview", "Stop"]);
});

test.each([
  {
    name: "unified patch input",
    input: { input: "*** Begin Patch\n*** Update File: docs/TESTING.md\n*** End Patch" },
  },
  {
    name: "JSON encoded replacement input",
    input: { input: JSON.stringify({ path: FIXTURE, oldText: "old", newText: "new" }) },
  },
  {
    name: "missing input",
    input: {},
  },
])("rejects %s with native edit guidance and leaves Stop clear", async ({ input }) => {
  const events: string[] = [];
  const handlers = createHarness(event => {
    events.push(event);
    return {};
  });
  const result = await handlers.get("tool_call")!(
    { toolName: "edit", toolCallId: "invalid-edit", input },
    ctx,
  );

  expect(result).toMatchObject({ block: true });
  expect(String((result as { reason?: unknown }).reason)).toContain("OMP edit");
  expect(events).toEqual([]);
  expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
});
