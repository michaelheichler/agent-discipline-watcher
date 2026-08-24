import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { createExtension } from "./index";
import {
  hashlinePaths,
  hookToolName,
  isPlainFilePath,
  isPostScanTool,
  isPreGateTool,
  normalizeArgs,
  postToolPaths,
  resolveRunner,
  runWatcher,
  type WatcherResult,
} from "./watcher";

type Handler = (event: unknown, ctx?: unknown) => Promise<unknown>;

function createHarness(run: (event: string, payload: Record<string, unknown>) => WatcherResult) {
  const handlers = new Map<string, Handler>();
  const sent: unknown[] = [];
  const pi = {
    on(eventName: string, handler: Handler) {
      handlers.set(eventName, handler);
    },
    async sendMessage(message: unknown, options: unknown) {
      sent.push({ message, options });
    },
  };
  createExtension(pi as never, run as never);
  return { handlers, sent };
}

function runScript(body: string): WatcherResult {
  const directory = mkdtempSync(join(tmpdir(), "adw-pi-test-"));
  const runner = join(directory, "runner.sh");
  writeFileSync(runner, `#!/bin/sh\n${body}\n`, { mode: 0o700 });
  try {
    return runWatcher("SessionStart", {}, runner);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

const ctx = {
  cwd: "/work",
  sessionManager: { getSessionId: () => "s1" },
};

describe("watcher helpers", () => {
  test("maps omp tool names to hook payloads", () => {
    expect(hookToolName("write")).toBe("Write");
    expect(hookToolName("bash")).toBe("Bash");
    expect(hookToolName("mcp__pi-agent_advise")).toBe("mcp__pi-agent_advise");
  });

  test("normalizes camelCase write arguments", () => {
    expect(normalizeArgs({ filePath: "a.ts", newString: "x" })).toEqual({
      file_path: "a.ts",
      new_string: "x",
    });
  });

  test("extracts hashline edit paths from patch headers", () => {
    const patch = "[src/a.ts#A1B2]\nPUT 1.=1:\n+ok\nMV lib/b.ts";
    expect(hashlinePaths(patch)).toEqual(["src/a.ts", "lib/b.ts"]);
  });

  test("uses resolvedPath for post-tool scans", () => {
    expect(postToolPaths({}, { resolvedPath: "src/x.ts" })).toEqual(["src/x.ts"]);
  });

  test("extracts hashline paths from edit result content", () => {
    expect(
      postToolPaths(
        {},
        undefined,
        [{ type: "text", text: "[lib/b.ts#NEW1]\nPUT 1.=1:\n+ok\n" }],
      ),
    ).toEqual(["lib/b.ts"]);
  });

  test("unions paths from input, details, and result content", () => {
    expect(
      postToolPaths(
        { input: "[src/a.ts#A1B2]\n" },
        { resolvedPath: "src/x.ts" },
        [{ type: "text", text: "[lib/b.ts#NEW1]\n" }],
      ),
    ).toEqual(["src/x.ts", "src/a.ts", "lib/b.ts"]);
  });

  test("skips non-plain write targets for pre-gates", () => {
    expect(isPlainFilePath("archive.zip:entry")).toBe(false);
    expect(isPlainFilePath("src/a.ts")).toBe(true);
    expect(isPreGateTool("write")).toBe(true);
    expect(isPreGateTool("edit")).toBe(false);
  });

  test("resolves the shared skill checkout runner", () => {
    expect(resolveRunner({ AGENT_DISCIPLINE_WATCHER_HOME: "/override" })).toEndWith("/override/hooks/run.sh");
  });

  test("fails closed when the runner exits non-zero", () => {
    const result = runScript("echo broken >&2; exit 1");
    expect(result.decision).toBe("block");
    expect(result.reason).toContain("broken");
  });
});

describe("omp event mapping", () => {
  test("blocks tool_call when PreToolUse runner throws", async () => {
    const { handlers } = createHarness(() => {
      throw new Error("runner unavailable");
    });
    const result = await handlers.get("tool_call")!(
      { toolName: "write", input: { path: "a.md", content: "bad" } },
      ctx,
    );
    expect(result).toEqual({ block: true, reason: "runner unavailable" });
  });

  test("blocks tool_call when PreToolUse denies", async () => {
    const events: string[] = [];
    const { handlers } = createHarness((event) => {
      events.push(event);
      return { decision: "block", reason: "fix punctuation" };
    });
    const result = await handlers.get("tool_call")!(
      { toolName: "write", input: { path: "a.md", content: "bad" } },
      ctx,
    );
    expect(result).toEqual({ block: true, reason: "fix punctuation" });
    expect(events).toEqual(["PreToolUse"]);
  });

  test("ignores read-only tools on post-scan", async () => {
    let calls = 0;
    const { handlers } = createHarness(() => {
      calls += 1;
      return {};
    });
    expect(isPostScanTool("read")).toBe(false);
    await handlers.get("tool_call")!(
      { toolName: "read", input: {} },
      ctx,
    );
    expect(calls).toBe(0);
    await handlers.get("tool_result")!(
      { toolName: "read", input: {}, content: [{ type: "text", text: "ok" }] },
      ctx,
    );
    expect(calls).toBe(0);
  });

  test("advises when edit result has no resolvable path", async () => {
    let calls = 0;
    const { handlers } = createHarness(() => {
      calls += 1;
      return {};
    });
    const result = await handlers.get("tool_result")!(
      {
        toolName: "edit",
        input: { input: "not a hashline patch" },
        content: [{ type: "text", text: "saved" }],
      },
      ctx,
    );
    expect(calls).toBe(0);
    expect(result).toEqual({
      content: [{
        type: "text",
        text: "saved\n\n[agent-discipline-watcher]\nagent-discipline-watcher could not resolve the edited file path from this edit result. Re-verify the touched file before finishing.",
      }],
    });
  });

  test("scans hashline edit paths from result content", async () => {
    const events: string[] = [];
    const { handlers } = createHarness((event, payload) => {
      const filePath = (payload as { tool_input?: { file_path?: string } }).tool_input?.file_path ?? "";
      events.push(`${event}:${filePath}`);
      return {};
    });
    await handlers.get("tool_result")!(
      {
        toolName: "edit",
        input: { input: "stale patch without headers" },
        content: [{ type: "text", text: "[lib/b.ts#NEW1]\nPUT 1.=1:\n+ok\n" }],
      },
      ctx,
    );
    expect(events).toEqual(["PostToolUse:lib/b.ts"]);
  });

  test("scans hashline edit paths from patch input", async () => {
    const events: string[] = [];
    const { handlers } = createHarness((event, payload) => {
      const filePath = (payload as { tool_input?: { file_path?: string } }).tool_input?.file_path ?? "";
      events.push(`${event}:${filePath}`);
      return {};
    });
    await handlers.get("tool_result")!(
      {
        toolName: "edit",
        input: { input: "[src/a.ts#A1B2]\nPUT 1.=1:\n+ok\nMV lib/b.ts" },
        content: [{ type: "text", text: "saved" }],
      },
      ctx,
    );
    expect(events).toEqual(["PostToolUse:src/a.ts", "PostToolUse:lib/b.ts"]);
  });

  test("sends only the resolved file_path to PostToolUse, not the raw write content", async () => {
    const payloads: Record<string, unknown>[] = [];
    const { handlers } = createHarness((event, payload) => {
      if (event === "PostToolUse") {
        payloads.push(payload);
      }
      return {};
    });
    await handlers.get("tool_result")!(
      {
        toolName: "write",
        input: { path: "a.md", content: "some file body that should not be re-sent" },
        content: [{ type: "text", text: "saved" }],
      },
      ctx,
    );
    expect(payloads).toEqual([
      {
        cwd: "/work",
        session_id: "s1",
        tool_name: "Write",
        tool_input: { file_path: "a.md" },
      },
    ]);
  });

  test("appends PostToolUse feedback to tool_result content", async () => {
    const { handlers } = createHarness((event) =>
      event === "PostToolUse"
        ? { systemMessage: "repair file", hookSpecificOutput: { additionalContext: "repair file" } }
        : {},
    );
    const result = await handlers.get("tool_result")!(
      {
        toolName: "edit",
        input: { file_path: "a.md" },
        content: [{ type: "text", text: "saved" }],
      },
      ctx,
    );
    expect(result).toEqual({
      content: [{ type: "text", text: "saved\n\n[agent-discipline-watcher]\nrepair file" }],
    });
  });

  test("maps Stop blocks to session_stop", async () => {
    const { handlers } = createHarness((event) =>
      event === "Stop" ? { decision: "block", reason: "repair touched files" } : {},
    );
    const result = await handlers.get("session_stop")!({}, ctx);
    expect(result).toEqual({ decision: "block", reason: "repair touched files" });
  });

  test.each([
    ["stop_hook_active", { stop_hook_active: true }],
    ["stopHookActive", { stopHookActive: true }],
  ])("forwards %s to Stop payload", async (_label, event) => {
    const payloads: Record<string, unknown>[] = [];
    const { handlers } = createHarness((hookEvent, payload) => {
      if (hookEvent === "Stop") {
        payloads.push(payload);
      }
      return {};
    });
    await handlers.get("session_stop")!(event, ctx);
    expect(payloads).toEqual([{ cwd: "/work", session_id: "s1", stop_hook_active: true }]);
  });

  test("injects SessionStart context on the next turn", async () => {
    const { handlers, sent } = createHarness((event) =>
      event === "SessionStart"
        ? { hookSpecificOutput: { additionalContext: "Lead with the next action." } }
        : {},
    );
    await handlers.get("session_start")!({}, ctx);
    expect(sent).toEqual([
      {
        message: {
          customType: "agent-discipline-watcher.context",
          content: "Lead with the next action.",
          display: false,
          attribution: "agent-discipline-watcher",
        },
        options: { deliverAs: "nextTurn", triggerTurn: false },
      },
    ]);
  });
});
