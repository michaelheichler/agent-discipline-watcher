import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createExtension } from "./index";

const roots: string[] = [];
type Handler = (event: unknown, ctx: unknown) => Promise<unknown>;
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

function harness() {
  const cwd = mkdtempSync(join(tmpdir(), "adw-observe-"));
  roots.push(cwd);
  const handlers = new Map<string, Handler>();
  const scans: string[] = [];
  const context = { cwd, sessionManager: { getSessionId: () => cwd } };
  const pi = { on: (name: string, handler: Handler) => handlers.set(name, handler), registerCommand() {}, async sendMessage() {} };
  createExtension(pi as never, (event, payload) => {
    if (event === "PostToolUse") scans.push(String((payload.tool_input as { file_path?: string }).file_path));
    return {};
  }, undefined, async () => ({}));
  return { cwd, scans, call: (name: string, event: unknown) => handlers.get(name)!(event, context) };
}

test.each(["eval", "hub"])("allows %s and scans actual writes even when execution fails", async toolName => {
  const h = harness();
  const path = join(h.cwd, "rule.mdc");
  writeFileSync(path, "Original content.\n");
  const input = toolName === "hub" ? { op: "start", application: "node", args: ["writer.js"] } :
    { language: "js", code: "const fs = await import('node:fs/promises'); await fs.writeFile(path, body);" };
  const event = { toolName, toolCallId: "observed", input };
  expect(await h.call("tool_call", event)).toBeUndefined();
  writeFileSync(path, "Updated content.\n");
  await h.call("tool_result", { ...event, isError: true, content: [{ type: "text", text: "throw after write" }] });
  expect(h.scans).toContain(path);
  expect(await h.call("session_stop", {})).toBeUndefined();
});

test("observes new files and delayed writes at Stop without scanning pre-existing changes", async () => {
  const h = harness();
  const existing = join(h.cwd, "existing.md");
  const created = join(h.cwd, "created.md");
  writeFileSync(existing, "Existing content.\n");
  const event = { toolName: "eval", toolCallId: "js", input: { language: "javascript", code: "let value = 1; display(value);" } };
  expect(await h.call("tool_call", event)).toBeUndefined();
  await h.call("tool_result", { ...event, content: [] });
  expect(h.scans).toEqual([]);
  writeFileSync(created, "New content.\n");
  expect(await h.call("session_stop", {})).toBeUndefined();
  expect(h.scans).toEqual([created]);
});

test("does not scan nested native writes twice", async () => {
  const h = harness();
  const outer = { toolName: "eval", toolCallId: "js", input: { language: "js", code: "const p = 'new.md'; await tool.write({path:p, content:'Saved.'});" } };
  expect(await h.call("tool_call", outer)).toBeUndefined();
  const path = join(h.cwd, "new.md");
  const inner = { toolName: "write", toolCallId: "write", input: { path, content: "Saved.\n" } };
  expect(await h.call("tool_call", inner)).toBeUndefined();
  writeFileSync(path, "Saved.\n");
  await h.call("tool_result", { ...inner, content: [] });
  await h.call("tool_result", { ...outer, content: [] });
  expect(h.scans).toEqual([path]);
});

test("reports inaccessible workspace coverage without blocking execution or Stop", async () => {
  const h = harness();
  rmSync(h.cwd, { recursive: true });
  const event = { toolName: "hub", toolCallId: "hub", input: { op: "list", path: "not-a-file" } };
  expect(await h.call("tool_call", event)).toBeUndefined();
  const result = await h.call("tool_result", { ...event, content: [] });
  expect(JSON.stringify(result)).toContain("observation was incomplete");
  expect(h.scans).toEqual([]);
  expect(await h.call("session_stop", {})).toBeUndefined();
});

test("does not turn deleted files into unresolved targets", async () => {
  const h = harness();
  const path = join(h.cwd, "removed.md");
  writeFileSync(path, "Remove this fixture.\n");
  const event = { toolName: "eval", toolCallId: "js", input: { language: "js", code: "await fs.unlink(path);" } };
  await h.call("tool_call", event);
  rmSync(path);
  await h.call("tool_result", { ...event, content: [] });
  expect(h.scans).toEqual([]);
  expect(await h.call("session_stop", {})).toBeUndefined();
});
