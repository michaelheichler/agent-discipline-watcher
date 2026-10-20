import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createExtension } from "./index";
import { adaptToolCall } from "./tool-adapter";
import type { WatcherResult } from "./watcher";

type Handler = (event: unknown, ctx: unknown) => Promise<unknown>;
type ToolCase = [string, string, Record<string, unknown>];

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

const GENERIC_REASON = adaptToolCall({ toolName: "unlisted_tool", input: {} }).reason;

const UNVERIFIABLE_JAVASCRIPT: ToolCase[] = [
  ["writes through node:fs", "eval", { language: "js", code: "import fs from 'node:fs'; fs.writeFileSync('a.md', 'body');" }],
  ["exits the process", "eval", { language: "javascript", code: "process.exit()" }],
];

const GENERIC_BLOCKS: ToolCase[] = [
  ["eval in an unsupported language", "eval", { language: "ruby", code: "File.write('a.md', 'body')" }],
  ["eval without a language", "eval", { code: "await tool.read({path:'a.md'});" }],
  ["an unknown tool name", "hub", { op: "start", application: "node", args: ["writer.js"] }],
  ["a non-Bash tool with a command field", "custom_runner", { command: "printf body > a.md" }],
  ["an MCP tool with a command field", "mcp__shell__run", { command: "printf body > a.md" }],
  ["a context note replacement", "context_notes", { text: "replace the notebook" }],
  ["an LSP action outside the read list", "lsp", { action: "rename_file" }],
  ["a debug action outside the read list", "debug", { action: "continue" }],
];

const ALLOWED_CALLS: ToolCase[] = [
  ["a display-wrapped JavaScript tool dispatch", "eval", { language: "js", code: "display(await tool.read({path:'a.md'}));" }],
  ["an unwrapped JavaScript tool dispatch", "eval", { language: "javascript", code: "await tool.read({path:'a.md'});" }],
  ["the read tool", "read", { path: "a.md" }],
  ["the grep tool", "grep", { pattern: "needle" }],
  ["the web search tool", "web_search", { query: "omp eval" }],
  ["a read-only LSP action", "lsp", { action: "hover" }],
  ["a read-only debug action", "debug", { action: "threads" }],
];

function harness(run: (event: string) => WatcherResult = () => ({})) {
  const cwd = mkdtempSync(join(tmpdir(), "adw-pre-block-"));
  roots.push(cwd);
  const handlers = new Map<string, Handler>();
  const context = { cwd, sessionManager: { getSessionId: () => cwd } };
  const pi = { on: (name: string, handler: Handler) => handlers.set(name, handler), registerCommand() {}, async sendMessage() {} };
  createExtension(pi as never, event => run(event), undefined, async () => ({}));
  return { cwd, call: (name: string, event: unknown) => handlers.get(name)!(event, context) };
}

test.each(UNVERIFIABLE_JAVASCRIPT)("blocks JavaScript eval that %s before it runs with the JavaScript reason", async (_shape, toolName, input) => {
  const result = await harness().call("tool_call", { toolName, toolCallId: "js", input }) as { block: boolean; reason: string };

  expect(result.block).toBe(true);
  expect(result.reason).not.toBe(GENERIC_REASON);
});

test.each(GENERIC_BLOCKS)("blocks %s before it runs with the generic reason", async (_shape, toolName, input) => {
  const result = await harness().call("tool_call", { toolName, toolCallId: "generic", input });

  expect(result).toEqual({ block: true, reason: GENERIC_REASON });
});

test.each(ALLOWED_CALLS)("lets %s run", async (_shape, toolName, input) => {
  expect(await harness().call("tool_call", { toolName, toolCallId: "allowed", input })).toBeUndefined();
});

test("blocks Stop after a tool result whose input cannot be decoded", async () => {
  const h = harness();
  await h.call("tool_result", { toolName: "write", input: { path: "a.md", file_path: "b.md" }, content: [] });

  expect(await h.call("session_stop", {})).toMatchObject({ decision: "block" });
});

test("leaves Stop open after OMP reports the failure of a blocked unknown tool", async () => {
  const h = harness(event => (event === "PostToolUse" ? { decision: "block", reason: "unverified file" } : {}));
  const target = join(h.cwd, "note.md");
  writeFileSync(target, "Existing note.\n");
  const event = { toolName: "custom_writer", toolCallId: "rejected", input: { path: target, content: "body" } };
  await h.call("tool_call", event);
  await h.call("tool_result", { ...event, isError: true, content: [{ type: "text", text: "blocked" }] });

  expect(await h.call("session_stop", {})).toBeUndefined();
});
