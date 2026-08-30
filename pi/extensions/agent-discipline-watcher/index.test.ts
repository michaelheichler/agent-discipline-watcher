import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { decodeAdwPolicy, sanitizeDisplay, type AdwBridgeRunner } from "./adw-config";

import { createExtension } from "./index";
import {
  canonicalPath,
  hashlinePaths,
  hookToolName,
  isMutatingTool,
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

function createHarness(
  run: (event: string, payload: Record<string, unknown>) => WatcherResult,
  bridge: AdwBridgeRunner = (() => ({})) as AdwBridgeRunner,
) {
  const handlers = new Map<string, Handler>();
  const commands = new Map<string, { handler: Handler }>();
  const sent: unknown[] = [];
  const pi = {
    on(eventName: string, handler: Handler) {
      handlers.set(eventName, handler);
    },
    registerCommand(name: string, spec: { handler: Handler }) {
      commands.set(name, spec);
    },
    async sendMessage(message: unknown, options: unknown) {
      sent.push({ message, options });
    },
  };
  createExtension(pi as never, run as never, bridge);
  return { handlers, commands, sent };
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

const TEST_CWD = process.cwd();
const ctx = {
  cwd: TEST_CWD,
  sessionManager: { getSessionId: () => "s1" },
};

function bridgeState(values: Record<string, unknown>, operation: string): Record<string, unknown> {
  return {
    ok: true,
    operation,
    project_path: TEST_CWD,
    config_path: `${TEST_CWD}/.agent-discipline.json`,
    digest: null,
    exists: operation === "write",
    values,
    effective: { adw_model: "" },
    families: [{ name: "punctuation", states: ["off", "observe", "enforce"], locked: false }],
    rules: [],
    always_blocking_rules: [],
    family_states: { punctuation: "enforce" },
    rule_states: {},
    runtime: { python: {}, embedding: {}, embedding_model: {} },
  };
}

test("OMP model selection reaches the guarded Save request", async () => {
  let saved: Record<string, unknown> | undefined;
  const bridge: AdwBridgeRunner = request => {
    if (request.operation === "write") {
      saved = request.values;
      return bridgeState(request.values ?? {}, "write");
    }
    return bridgeState({}, request.operation);
  };
  const { commands } = createHarness(() => ({}), bridge);
  const command = commands.get("adw");
  if (!command) throw new Error("ADW command was not registered");
  const commandContext = {
    cwd: TEST_CWD,
    hasUI: true,
    models: { list: () => [{ provider: "anthropic", id: "claude-haiku-4-5" }, { provider: "anthropic", id: "claude-sonnet-5" }, { provider: "openai-codex", id: "gpt-5.6" }] },
    ui: {
      notify() {},
      async custom(factory: (tui: unknown, theme: unknown, keys: unknown, done: (result: string) => void) => { handleInput?(data: string): void }) {
        let outcome: string | undefined;
        const component = factory({ requestRender() {} }, {}, {}, result => {
          outcome = result;
        });
        for (let index = 0; index < 7; index += 1) component.handleInput?.("\u001b[B");
        component.handleInput?.("\r");
        component.handleInput?.("\r");
        component.handleInput?.("\u001b");
        for (let index = 0; index < 9; index += 1) component.handleInput?.("\u001b[B");
        component.handleInput?.("\r");
        await Promise.resolve();
        await Promise.resolve();
        return outcome;
      },
    },
  };

  await command.handler("configure", commandContext);

  expect(saved?.adw_model).toBe("claude-haiku-4-5");
});

describe("judge availability warning", () => {
  function configureContext(notices: Array<{ message: string; type?: string }>) {
    return {
      cwd: TEST_CWD,
      hasUI: true,
      models: { list: () => [] },
      ui: {
        notify(message: string, type?: string) {
          notices.push({ message, type });
        },
        async custom() {
          return "cancelled";
        },
      },
    };
  }

  test("warns that model judges stay inactive while the data boundary is off", async () => {
    const notices: Array<{ message: string; type?: string }> = [];
    const bridge: AdwBridgeRunner = request => bridgeState({}, request.operation);
    const { commands } = createHarness(() => ({}), bridge);
    const command = commands.get("adw");
    if (!command) throw new Error("ADW command was not registered");

    await command.handler("configure", configureContext(notices));

    expect(notices).toContainEqual({
      message: "Data boundary is off, so every model judge stays inactive and only the regex rules run.",
      type: "warning",
    });
  });

  test("stays quiet about judges once the data boundary is on", async () => {
    const notices: Array<{ message: string; type?: string }> = [];
    const bridge: AdwBridgeRunner = request => ({
      ...bridgeState({}, request.operation),
      effective: { adw_model: "", data_boundary: { enabled: true } },
    });
    const { commands } = createHarness(() => ({}), bridge);
    const command = commands.get("adw");
    if (!command) throw new Error("ADW command was not registered");

    await command.handler("configure", configureContext(notices));

    expect(notices.some(notice => notice.message.includes("model judge"))).toBe(false);
  });
});

describe("watcher helpers", () => {
  test("maps omp tool names to hook payloads", () => {
    expect(hookToolName("write")).toBe("Write");
    expect(hookToolName("bash")).toBe("Bash");
    expect(hookToolName("mcp__pi-agent_advise")).toBe("mcp__pi-agent_advise");
  });


  test("registers separate ADW commands without touching the advisor command", () => {
    const { commands } = createHarness(() => ({}));
    expect([...commands.keys()]).toEqual(["adw", "agent-discipline"]);
  });

  test("sanitizes bridge values before OMP rendering", () => {
    expect(sanitizeDisplay("\u001b[31mprivate\u001b[0m\n<markup>", 64)).toBe("private <markup>");
    const state = decodeAdwPolicy({
      ok: true,
      digest: null,
      values: { exempt_paths: ["safe", "\u001b[31munsafe"] },
      effective: {},
      families: [],
      rules: [],
      always_blocking_rules: [],
      family_states: {},
      rule_states: {},
      runtime: {},
    });
    expect(state.values.exempt_paths).toEqual(["safe"]);
  });

  test("normalizes camelCase write arguments", () => {
    expect(normalizeArgs({ filePath: "a.ts", newString: "x" })).toEqual({
      file_path: "a.ts",
      new_string: "x",
    });
  });
  test("rejects conflicting path aliases before dispatch", () => {
    expect(() => normalizeArgs({ path: "src/a.ts", file_path: "src/b.ts" })).toThrow(
      "conflicting path aliases",
    );
  });

  test("canonicalizes supported target aliases and preserves edit text", () => {
    expect(
      normalizeArgs({
        notebookPath: "src/notebook.ipynb",
        newSource: "  indented source\n",
        input: "[src/notebook.ipynb#A1B2]\n",
      }),
    ).toEqual({
      file_path: "src/notebook.ipynb",
      new_string: "  indented source\n",
      input: "[src/notebook.ipynb#A1B2]\n",
    });
  });

  test("rejects conflicting patch aliases", () => {
    expect(() => normalizeArgs({ patch: "one", input: "two" })).toThrow(
      "conflicting patch aliases",
    );
  });

  test("canonicalizes targets under the session cwd", () => {
    expect(canonicalPath("src/a.ts", TEST_CWD)).toBe(`${TEST_CWD}/src/a.ts`);
    expect(canonicalPath("../outside.ts", TEST_CWD)).toBeUndefined();
    expect(canonicalPath("/etc/hosts", TEST_CWD)).toBeUndefined();
    expect(canonicalPath("src/\u0000a.ts", TEST_CWD)).toBeUndefined();
  });

  test("pre-gates every mutating file tool", () => {
    for (const tool of ["write", "edit", "multiedit", "notebookedit", "apply_patch", "bash"]) {
      expect(isMutatingTool(tool)).toBe(true);
      expect(isPreGateTool(tool)).toBe(true);
      expect(isPostScanTool(tool)).toBe(true);
    }
  });

  test("extracts hashline edit paths from patch headers", () => {
    const patch = "[src/a.ts#A1B2]\nPUT 1.=1:\n+ok\nMV lib/b.ts";
    expect(hashlinePaths(patch)).toEqual(["src/a.ts", "lib/b.ts"]);
  });

  test("ignores unverified resolvedPath for post-tool scans", () => {
    expect(postToolPaths({}, { resolvedPath: "src/x.ts", pathVerified: true })).toEqual([]);
  });

  test("ignores uncorrelated hashline paths from edit result content", () => {
    expect(
      postToolPaths(
        {},
        undefined,
        [{ type: "text", text: "[lib/b.ts#NEW1]\nPUT 1.=1:\n+ok\n" }],
      ),
    ).toEqual([]);
  });

  test("keeps input-derived paths while rejecting forged result paths", () => {
    expect(
      postToolPaths(
        { input: "[src/a.ts#A1B2]\n" },
        { resolvedPath: "src/x.ts", pathVerified: true },
        [{ type: "text", text: "[lib/b.ts#NEW1]\n" }],
      ),
    ).toEqual(["src/a.ts"]);
  });

  test("canonicalizes and correlates result paths under cwd", () => {
    expect(
      postToolPaths(
        { path: "src/a.ts" },
        undefined,
        [{ type: "text", text: "[src/a.ts#A1B2]\n[../outside#BAD1]\n" }],
        TEST_CWD,
      ),
    ).toEqual([`${TEST_CWD}/src/a.ts`]);
  });


  test("skips non-plain write targets for pre-gates", () => {
    expect(isPlainFilePath("archive.zip:entry")).toBe(false);
    expect(isPlainFilePath("src/a.ts")).toBe(true);
    expect(isPreGateTool("write")).toBe(true);
    expect(isPreGateTool("edit")).toBe(true);
  });

  test("prefers the runner inside the state directory", () => {
    expect(resolveRunner({}, "/home/tester", () => true)).toBe(
      "/home/tester/.adw/install/agent-discipline-watcher/hooks/run.sh",
    );
  });

  test("falls back to the legacy link when the state directory has no runner", () => {
    expect(resolveRunner({}, "/home/tester", () => false)).toBe(
      "/home/tester/.agents/skills/agent-discipline-watcher/hooks/run.sh",
    );
  });

  test("an explicit override wins over both locations", () => {
    expect(resolveRunner({ AGENT_DISCIPLINE_WATCHER_HOME: "/override" }, "/home/tester", () => true))
      .toBe("/override/hooks/run.sh");
  });

  test("fails closed when the runner exits non-zero", () => {
    const result = runScript("echo broken >&2; exit 1");
    expect(result.decision).toBe("block");
    expect(result.reason).toContain("broken");
  });
  test("fails closed on malformed runner JSON and result fields", () => {
    expect(runScript("printf '%s' 'not-json'")).toEqual({
      decision: "block",
      reason: "SessionStart watcher returned malformed JSON",
    });
    expect(runScript("printf '%s' '{\"decision\":123}'")).toEqual({
      decision: "block",
      reason: "SessionStart watcher returned malformed output",
    });
  });

  test("bounds runner input before invoking the runner", () => {
    const result = runWatcher("SessionStart", { content: "x".repeat(1_000_001) }, "/missing/runner");
    expect(result).toEqual({
      decision: "block",
      reason: "SessionStart watcher input exceeded its size limit",
    });
  });
  test("fails closed when runner output exceeds its limit", () => {
    const result = runScript("printf '%65537s' ''");
    expect(result.decision).toBe("block");
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
  test.each(["write", "edit", "multiedit", "notebookedit", "apply_patch"])(
    "advises when %s has no trusted post-tool target",
    async (toolName) => {
      let calls = 0;
      const { handlers } = createHarness(() => {
        calls += 1;
        return {};
      });
      const result = await handlers.get("tool_result")!(
        {
          toolName,
          input: {},
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
    },
  );

  test("leaves a bash result alone when it names no write target", async () => {
    let calls = 0;
    const { handlers } = createHarness(() => {
      calls += 1;
      return {};
    });
    const result = await handlers.get("tool_result")!(
      {
        toolName: "bash",
        input: { command: "ls" },
        content: [{ type: "text", text: "ok" }],
      },
      ctx,
    );
    expect(calls).toBe(0);
    expect(result).toBeUndefined();
  });

  test("keeps Stop open after a bash result with no write target", async () => {
    const { handlers } = createHarness(() => ({}));
    await handlers.get("tool_result")!(
      {
        toolName: "bash",
        input: { command: "git status" },
        content: [{ type: "text", text: "clean" }],
      },
      ctx,
    );
    expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
  });

  test("keeps Stop open after a failed bash result", async () => {
    const { handlers } = createHarness(() => ({}));
    await handlers.get("tool_result")!(
      {
        toolName: "bash",
        input: { command: "false" },
        content: [{ type: "text", text: "exit 1" }],
        isError: true,
      },
      ctx,
    );
    expect(await handlers.get("session_stop")!({}, ctx)).toBeUndefined();
  });

  test("still scans a bash result that names a hashline target", async () => {
    const events: string[] = [];
    const { handlers } = createHarness((event, payload) => {
      const filePath = (payload as { tool_input?: { file_path?: string } }).tool_input?.file_path ?? "";
      events.push(`${event}:${filePath}`);
      return {};
    });
    await handlers.get("tool_result")!(
      {
        toolName: "bash",
        input: { command: "[src/a.ts#A1B2]" },
        content: [{ type: "text", text: "saved" }],
      },
      ctx,
    );
    expect(events).toEqual([
      `PostToolUse:${TEST_CWD}/src/a.ts`,
      `JudgeReview:${TEST_CWD}/src/a.ts`,
    ]);
  });

  test("blocks Stop after an unresolved mutating result", async () => {
    const { handlers } = createHarness(() => ({}));
    await handlers.get("tool_result")!(
      {
        toolName: "write",
        input: {},
        content: [{ type: "text", text: "saved" }],
      },
      ctx,
    );
    const result = await handlers.get("session_stop")!({}, ctx);
    expect(result).toEqual({
      decision: "block",
      reason: "agent-discipline-watcher could not verify every mutating tool result. Re-verify the touched file before stopping.",
    });
  });
  test("keeps Stop blocked after unresolved result followed by valid result", async () => {
    const { handlers } = createHarness(() => ({}));
    await handlers.get("tool_result")!(
      {
        toolName: "write",
        input: {},
        content: [{ type: "text", text: "saved" }],
      },
      ctx,
    );
    await handlers.get("tool_result")!(
      {
        toolName: "write",
        input: { path: "a.md", content: "clean" },
        content: [{ type: "text", text: "saved" }],
      },
      ctx,
    );
    const result = await handlers.get("session_stop")!({}, ctx);
    expect(result).toEqual({
      decision: "block",
      reason: "agent-discipline-watcher could not verify every mutating tool result. Re-verify the touched file before stopping.",
    });
  });

  test("rejects uncorrelated hashline paths from edit result content", async () => {
    const events: string[] = [];
    const { handlers } = createHarness((event, payload) => {
      const toolInput = payload.tool_input;
      const filePath =
        toolInput && typeof toolInput === "object" && !Array.isArray(toolInput) &&
        "file_path" in toolInput && typeof toolInput.file_path === "string"
          ? toolInput.file_path
          : "";
      events.push(`${event}:${filePath}`);
      return {};
    });
    const result = await handlers.get("tool_result")!(
      {
        toolName: "edit",
        input: { input: "stale patch without headers" },
        content: [{ type: "text", text: "[lib/b.ts#NEW1]\nPUT 1.=1:\n+ok\n" }],
      },
      ctx,
    );
    expect(events).toEqual([]);
    if (!result || typeof result !== "object" || !("content" in result) || !Array.isArray(result.content)) {
      throw new Error("expected a tool-result content response");
    }
    const first = result.content[0];
    if (!first || typeof first !== "object" || !("text" in first) || typeof first.text !== "string") {
      throw new Error("expected a text tool-result chunk");
    }
    expect(first.text).toContain("could not resolve the edited file path");
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
    expect(events).toEqual([
      `PostToolUse:${TEST_CWD}/src/a.ts`,
      `JudgeReview:${TEST_CWD}/src/a.ts`,
      `PostToolUse:${TEST_CWD}/lib/b.ts`,
      `JudgeReview:${TEST_CWD}/lib/b.ts`,
    ]);
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
        cwd: TEST_CWD,
        session_id: "s1",
        tool_name: "Write",
        tool_input: { file_path: `${TEST_CWD}/a.md` },
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
    expect(payloads).toEqual([{ cwd: TEST_CWD, session_id: "s1", stop_hook_active: true }]);
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
  test("sends SessionStart block reasons as user-visible diagnostics", async () => {
    const { handlers, sent } = createHarness(() => ({
      decision: "block",
      reason: "repair the blocked startup state",
    }));
    await handlers.get("session_start")!({}, ctx);
    expect(sent[0]).toEqual({
      message: {
        customType: "agent-discipline-watcher.context",
        content: "repair the blocked startup state",
        display: false,
        attribution: "agent-discipline-watcher",
      },
      options: { deliverAs: "nextTurn", triggerTurn: false },
    });
  });
});
