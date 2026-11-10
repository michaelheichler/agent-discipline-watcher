import { expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createExtension } from "./index";
import { adaptToolCall } from "./tool-adapter";
import { inspectMcp } from "./mcp-contract";
import type { WatcherResult } from "./watcher";

type Handler = (event: unknown, context: unknown) => Promise<unknown>;
const HOOKS = resolve(import.meta.dir, "../../../hooks");
type GoldenCase = {
  tool_name: string; arguments: Record<string, unknown>; targets?: string[];
  operation?: string[]; mutation?: boolean; error?: boolean;
};
const GOLDEN: GoldenCase[] = JSON.parse(readFileSync(join(HOOKS, "lib/fixtures/mcp_golden.json"), "utf8"));
const LIMITS = JSON.parse(readFileSync(join(HOOKS, "lib/mcp_contract.json"), "utf8"));

test.each(GOLDEN.filter(row => !row.error))("shares golden MCP classification %#", row => {
  const actual = inspectMcp(row.tool_name, row.arguments);

  expect(actual.targets).toEqual(row.targets);
  expect(actual.operations).toEqual(row.operation);
  expect(actual.mutation).toBe(row.mutation);
});

test.each(GOLDEN.filter(row => row.error))("rejects golden unsafe MCP URI %#", row => {
  expect(() => inspectMcp(row.tool_name, row.arguments)).toThrow();
});

function deepArguments(depth: number): Record<string, unknown> {
  let value: Record<string, unknown> = {};
  for (let index = 0; index < depth; index++) value = { payload: value };
  return value;
}

test.each([
  { payload: Array(LIMITS.max_argument_nodes - 2).fill(null) },
  deepArguments(LIMITS.max_argument_depth),
])("accepts the shared MCP inspection boundary %#", input => {
  expect(inspectMcp("mcp__files__read", input).targets).toEqual([]);
});

test.each([
  { payload: Array(LIMITS.max_argument_nodes - 1).fill(null) },
  deepArguments(LIMITS.max_argument_depth + 1),
])("rejects arguments beyond the shared MCP inspection boundary %#", input => {
  expect(() => inspectMcp("mcp__files__read", input)).toThrow();
});

const PATH_ALIASES = [
  "path", "file", "file_path", "filePath", "relative_path", "relativePath", "source",
  "source_path", "sourcePath", "source_file", "sourceFile", "destination", "destination_path",
  "destinationPath", "destination_file", "destinationFile", "target", "target_path", "targetPath",
  "target_file", "targetFile", "file_name", "fileName", "filename", "notebook_path", "notebookPath",
  "old_path", "oldPath", "new_path", "newPath", "output_path", "outputPath", "uri", "file_uri",
  "fileUri", "fileURI", "outputFile", "targetUri", "URIPath",
];
const BODY_ALIASES = [
  "content", "contents", "text", "data", "body", "new_string", "newString", "new_source",
  "newSource", "file_text", "fileText", "new_text", "newText",
];

function python(input: unknown, code: string, home: string): unknown {
  const result = spawnSync(process.env.ADW_PYTHON ?? "python3", [
    "-I", "-S", "-c", `import sys; sys.path.insert(0, ${JSON.stringify(HOOKS)}); ${code}`,
  ], { input: JSON.stringify(input), encoding: "utf8", cwd: home, env: { ...process.env, HOME: home } });
  expect(result.status).toBe(0);
  return JSON.parse(result.stdout);
}

function extracted(input: unknown): unknown {
  return python(input,
    "import json; from lib.mcp_paths import mcp_target_paths, mcp_write_contents; " +
    "value=json.load(sys.stdin); print(json.dumps({'paths':mcp_target_paths(value),'contents':mcp_write_contents(value)}))",
    tmpdir());
}

test.each(PATH_ALIASES)("shares MCP target extraction for %s with Python", alias => {
  const input = { [alias]: "a.md", body: "replacement" };
  const adapted = adaptToolCall({ toolName: "mcp__docs__save_document", input });

  expect(extracted(input)).toEqual({ paths: ["a.md"], contents: ["replacement"] });
  expect(adapted).toMatchObject({ kind: "mcp", requiresTarget: true, targetPaths: ["a.md"] });
});

test.each(["paths", "files", "targets"])("shares MCP target arrays for %s", alias => {
  const input = { [alias]: ["a.md", "", "b.md"], body: "replacement" };
  expect(extracted(input)).toEqual({ paths: ["a.md", "b.md"], contents: ["replacement"] });
  expect(adaptToolCall({ toolName: "mcp__docs__save_document", input }).targetPaths).toEqual(["a.md", "b.md"]);
});

test.each(["old_string", "oldString", "patch", "edits", "source_metadata"])(
  "does not mistake %s text for an MCP target", alias => {
    const input = { filePath: "a.md", body: "replacement", [alias]: "not-a-path" };
    expect(extracted(input)).toEqual({ paths: ["a.md"], contents: ["replacement"] });
    expect(adaptToolCall({ toolName: "mcp__docs__save_document", input }).targetPaths).toEqual(["a.md"]);
  },
);

test.each([
  ...BODY_ALIASES, "edits", "patch", "replacement", "replacements", "old_string", "oldString",
  "source_metadata",
])("never treats scalar %s data as an MCP target without a path", alias => {
  const input = { [alias]: "a.md" };

  expect((extracted(input) as { paths: string[] }).paths).toEqual([]);
  expect(adaptToolCall({ toolName: "mcp__docs__save_document", input }).targetPaths ?? []).toEqual([]);
});

test.each(BODY_ALIASES)("recognizes an unknown MCP writer using %s", alias => {
  const input = { relativePath: "a.md", [alias]: "replacement" };

  expect(extracted(input)).toEqual({ paths: ["a.md"], contents: ["replacement"] });
  expect(adaptToolCall({ toolName: "mcp__docs__save_document", input })).toMatchObject({
    kind: "mcp", requiresTarget: true, targetPaths: ["a.md"],
  });
});

test.each([
  [{ edits: [{ filePath: "a.md", body: "replacement" }] }, ["a.md"], ["replacement"]],
  [{ paths: ["a.md", "", "b.md"], body: "" }, ["a.md", "b.md"], []],
  [{ uri: "file:///tmp/a%20b.md", newText: "replacement" }, ["/tmp/a b.md"], ["replacement"]],
])("shares nested and ambiguous MCP targets without losing candidates %j", (input, paths, contents) => {
  expect(extracted(input)).toEqual({ paths, contents });
  expect(adaptToolCall({ toolName: "mcp__docs__save_document", input }).targetPaths).toEqual(paths);
});

test("preserves all conflicting MCP target candidates for Python inspection", () => {
  const input = { file_path: "a.md", filePath: "b.md", body: "replacement" };

  expect(extracted(input)).toEqual({ paths: ["a.md", "b.md"], contents: ["replacement"] });
  expect(adaptToolCall({ toolName: "mcp__docs__save_document", input })).toMatchObject({
    targetPaths: ["a.md", "b.md"], input,
  });
});

function handlersFor(run: (event: string, payload: Record<string, unknown>) => WatcherResult): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  createExtension({
    on: (name: string, handler: Handler) => handlers.set(name, handler),
    registerCommand() {}, async sendMessage() {},
  } as never, run as never, undefined as never, async () => ({}));
  return handlers;
}

function pythonGate(root: string, payload: Record<string, unknown>): WatcherResult {
  return python({ ...payload, roots: root },
    "import json; from pre_mcp import run; from pathlib import Path; " +
    "value=json.load(sys.stdin); root=Path(value.pop('roots')); " +
    "print(json.dumps(run(value, {'state_root':str(root/'state'),'ledger_root':str(root/'ledger')})))",
    root) as WatcherResult;
}

test("blocks an MCP policy weakening through the registered handler and real Python gate", async () => {
  const root = mkdtempSync(join(tmpdir(), "adw-mcp-gate-"));
  writeFileSync(join(root, ".agent-discipline.json"), "{}");
  const events: string[] = [];
  const handlers = handlersFor((event, payload) => {
    events.push(event);
    return pythonGate(root, payload);
  });
  try {
    const result = await handlers.get("tool_call")!({
      toolName: "mcp__docs__save_document", toolCallId: "sealed-policy",
      input: { filePath: ".agent-discipline.json", body: '{"tests":"allow"}' },
    }, { cwd: root, sessionManager: { getSessionId: () => "mcp-seal" } });

    expect(result).toMatchObject({ block: true, reason: expect.stringContaining("config_seal") });
    expect(events).toEqual(["PreToolUse"]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test.each(["file_path", "filePath"])(
  "inspects both conflicting aliases in Python when %s targets protected policy", async protectedKey => {
    const root = mkdtempSync(join(tmpdir(), "adw-mcp-conflict-"));
    writeFileSync(join(root, ".agent-discipline.json"), "{}");
    const input: Record<string, unknown> = {
      file_path: "ordinary.md", filePath: "ordinary.md", body: "replacement",
    };
    input[protectedKey] = ".agent-discipline.json";
    const calls: { event: string; input: unknown }[] = [];
    const handlers = handlersFor((event, payload) => {
      calls.push({ event, input: payload.tool_input });
      return pythonGate(root, payload);
    });
    try {
      const result = await handlers.get("tool_call")!({
        toolName: "mcp__docs__save_document", input,
      }, { cwd: root, sessionManager: { getSessionId: () => "protected-conflict" } });

      expect(result).toMatchObject({ block: true, reason: expect.stringContaining("config_seal") });
      expect(calls).toEqual([{ event: "PreToolUse", input }]);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  },
);

test.each([{ query: "needle" }, { path: "a.md" }, { filters: { tag: "docs" } }])(
  "passes unknown read-only MCP shapes through the Python gate %j", async input => {
    const events: string[] = [];
    const handlers = handlersFor(event => { events.push(event); return {}; });

    const result = await handlers.get("tool_call")!({ toolName: "mcp__docs__lookup", input }, {
      cwd: tmpdir(), sessionManager: { getSessionId: () => "mcp-read" },
    });

    expect(result).toBeUndefined();
    expect(events).toEqual(["PreToolUse"]);
  },
);

test("sends both conflicting MCP target candidates to the Python gate", async () => {
  const payloads: Record<string, unknown>[] = [];
  const handlers = handlersFor((_event, payload) => { payloads.push(payload); return {}; });
  const input = { file_path: "a.md", filePath: "b.md", body: "replacement" };

  const result = await handlers.get("tool_call")!({ toolName: "mcp__docs__save_document", input }, {
    cwd: tmpdir(), sessionManager: { getSessionId: () => "conflicting-mcp" },
  });

  expect(result).toBeUndefined();
  expect(payloads).toEqual([expect.objectContaining({ tool_input: input })]);
});

test("preserves nested MCP edit content at the Python pre-gate boundary", async () => {
  const payloads: Record<string, unknown>[] = [];
  const events: string[] = [];
  const handlers = handlersFor((event, payload) => { events.push(event); payloads.push(payload); return {}; });
  const input = { path: "a.md", edits: [{ newText: "replacement" }] };

  const result = await handlers.get("tool_call")!({ toolName: "mcp__docs__save_document", input }, {
    cwd: tmpdir(), sessionManager: { getSessionId: () => "nested-mcp" },
  });

  expect(result).toBeUndefined();
  expect(events).toEqual(["PreToolUse"]);
  expect(payloads).toEqual([expect.objectContaining({ tool_input: expect.objectContaining({ edits: input.edits }) })]);
  expect(payloads[0]?.tool_input).not.toHaveProperty("new_string");
});

test("runs the Python gate before rejecting an unresolved named MCP write", async () => {
  const events: string[] = [];
  const handlers = handlersFor(event => { events.push(event); return {}; });

  const result = await handlers.get("tool_call")!({
    toolName: "mcp__docs__write_document", input: { unmapped: "a.md", body: "replacement" },
  }, { cwd: tmpdir(), sessionManager: { getSessionId: () => "unresolved-mcp" } });

  expect(result).toMatchObject({ block: true });
  expect(events).toEqual(["PreToolUse"]);
});

function nestedArguments(depth: number): Record<string, unknown> {
  let input: Record<string, unknown> = { filePath: "a.md", body: "replacement" };
  for (let level = 0; level < depth; level += 1) input = { editPayload: input };
  return input;
}

const BOUNDED_ARGUMENTS = [
  ["deep", nestedArguments(14)],
  ["wide", { edits: Array(4097).fill({ body: "replacement" }) }],
] as const;

test.each(BOUNDED_ARGUMENTS)("rejects %s MCP argument graphs at the OMP boundary", async (_label, input) => {
  const handlers = handlersFor(() => ({}));

  const result = await handlers.get("tool_call")!({ toolName: "mcp__docs__save_document", input }, {
    cwd: tmpdir(), sessionManager: { getSessionId: () => "bounded-mcp" },
  });

  expect(result).toMatchObject({ block: true });
});

test.each(BOUNDED_ARGUMENTS)("rejects %s MCP argument graphs at the Python boundary", (_label, input) => {
  const root = mkdtempSync(join(tmpdir(), "adw-mcp-bounds-"));
  const payload = { tool_name: "mcp__docs__save_document", cwd: root, tool_input: input };
  try {
    expect(pythonGate(root, payload)).toMatchObject({ decision: "block" });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("falls back to the Python gate when the MCP contract is unavailable", () => {
  const root = mkdtempSync(join(tmpdir(), "adw-mcp-contract-"));
  cpSync(HOOKS, join(root, "hooks"), { recursive: true });
  rmSync(join(root, "hooks/lib/mcp_contract.json"), { force: true });
  const gate = `import sys,json; sys.path.insert(0, ${JSON.stringify(join(root, "hooks"))}); ` +
    "from pre_mcp import run; from pathlib import Path; root=Path.cwd(); " +
    "print(json.dumps(run(json.load(sys.stdin), {'state_root':str(root/'state'),'ledger_root':str(root/'ledger')})))";
  const source = `
    const {spawnSync} = await import('node:child_process');
    const {createExtension} = await import(${JSON.stringify(resolve(import.meta.dir, "index.ts"))});
    const handlers = new Map(); const events = [];
    const run = (event,payload) => {
      events.push(event);
      const child=spawnSync(${JSON.stringify(process.env.ADW_PYTHON ?? "python3")},
        ['-I','-S','-c',${JSON.stringify(gate)}], {input:JSON.stringify(payload),encoding:'utf8'});
      if(child.status!==0) throw new Error(child.stderr);
      return JSON.parse(child.stdout);
    };
    createExtension({on:(name,handler)=>handlers.set(name,handler),registerCommand(){},async sendMessage(){}},
      run, undefined, async()=>({}));
    const result = await handlers.get('tool_call')({toolName:'mcp__docs__save_document',
      input:{filePath:'a.md',body:'replacement'}},
      {cwd:process.cwd(),sessionManager:{getSessionId:()=> 'missing-contract'}});
    console.log(JSON.stringify({result,events}));
  `;
  try {
    const child = spawnSync(process.execPath, ["-e", source], {
      encoding: "utf8", cwd: root,
      env: { ...process.env, HOME: root, AGENT_DISCIPLINE_WATCHER_HOME: root },
    });

    expect(child.status).toBe(0);
    expect(JSON.parse(child.stdout)).toMatchObject({ result: { block: true }, events: ["PreToolUse"] });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
