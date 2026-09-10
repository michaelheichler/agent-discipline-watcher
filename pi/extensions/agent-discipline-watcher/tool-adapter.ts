import { normalizeArgs } from "./watcher";
import { isToolDispatch } from "./js-dispatch";

const DIRECT_TOOL_NAMES: Record<string, string> = {
  write: "Write",
  edit: "Edit",
  multiedit: "MultiEdit",
  notebookedit: "NotebookEdit",
  notebook: "NotebookEdit",
  write_notebook: "NotebookEdit",
  apply_patch: "apply_patch",
  bash: "Bash",
};

const READ_TOOLS = new Set(["read", "grep", "glob", "ls", "find"]);
const SAFE_NON_MUTATING_TOOLS = new Set([
  "ask",
  "ast_grep",
  "goal",
  "think",
  "yield",
  "task",
  "todo",
  "web_search",
  "security_scan",
]);
const DEBUG_READ_ACTIONS = new Set([
  "output",
  "threads",
  "stack_trace",
  "scopes",
  "variables",
  "disassemble",
  "read_memory",
  "loaded_sources",
  "modules",
  "sessions",
]);
const LSP_READ_ACTIONS = new Set([
  "diagnostics",
  "definition",
  "type_definition",
  "implementation",
  "references",
  "hover",
  "symbols",
  "status",
  "capabilities",
]);
const NOTEBOOK_READ_OPERATIONS = new Set(["read", "inspect", "list", "show"]);
const WRITE_OPERATIONS = new Set([
  "append",
  "create",
  "delete",
  "edit",
  "move",
  "patch",
  "remove",
  "rename",
  "update",
  "write",
]);
const DELETE_OPERATIONS = new Set(["delete", "remove"]);
const MCP_PATH_KEYS = ["path", "file_path", "relative_path", "source", "destination"] as const;
const MCP_CONTENT_KEYS = ["content", "contents", "text", "data", "new_string", "new_source", "file_text"] as const;
const REPORT_PATH_ALIASES = ["file_path", "filePath", "notebook_path", "notebookPath"] as const;
export type MutationKind = "read" | "write" | "bash" | "mcp" | "notebook" | "python" | "host-report" | "unknown-write" | "other";

export type OmpToolEvent = {
  toolName: string;
  toolCallId?: string;
  input?: Record<string, unknown>;
  details?: unknown;
  content?: Array<{ type: string; text?: string }>;
  isError?: boolean;
};

export type AdaptedTool = {
  kind: MutationKind;
  hookToolName: string;
  input: Record<string, unknown>;
  requiresTarget: boolean;
  targetPaths?: string[];
  deletedTargetPaths?: string[];
  preGateInputs?: Record<string, unknown>[];
  reason?: string;
};

export type TargetResolver = (toolName: string, input: Record<string, unknown>) => readonly string[];

const UNKNOWN_WRITE_REASON =
  "agent-discipline-watcher could not classify this OMP tool as a safe mutation.";
const UNSUPPORTED_JAVASCRIPT_REASON =
  "agent-discipline-watcher cannot verify this JavaScript eval. Use literal await tool.name({...}) calls, optionally wrapped in display(...), so nested tools can be checked.";

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function pythonInput(code: string): AdaptedTool {
  return {
    kind: "python",
    hookToolName: "Python",
    input: { code },
    requiresTarget: false,
  };
}

function operationValue(input: Record<string, unknown>): string | undefined {
  for (const key of ["operation", "action", "mode", "method"]) {
    const value = stringValue(input[key]);
    if (value) return value.toLowerCase();
  }
  return undefined;
}

function unique(values: readonly (string | undefined)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
}

function stringList(value: unknown): string[] {
  if (typeof value === "string") return value.trim() ? [value] : [];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()));
}

function mcpTargetPaths(input: Record<string, unknown>): string[] {
  const paths: string[] = [];
  for (const key of MCP_PATH_KEYS) paths.push(...stringList(input[key]));
  paths.push(...stringList(input.paths));
  return unique(paths);
}

function mcpHasContent(input: Record<string, unknown>): boolean {
  return MCP_CONTENT_KEYS.some(key => Object.prototype.hasOwnProperty.call(input, key));
}

function mcpNameHasOperation(toolName: string, operations: ReadonlySet<string>): boolean {
  const name = toolName.split("__").slice(2).join("__");
  const parts = name.replace(/([a-z0-9])([A-Z])/gu, "$1_$2").toLowerCase().match(/[a-z0-9]+/gu) ?? [];
  const operation = parts[0] === "batch" ? parts[1] : parts[0];
  return operations.has(operation ?? "");
}

function mcpIsMutation(toolName: string, input: Record<string, unknown>): boolean {
  const operation = operationValue(input);
  return Boolean(
    mcpNameHasOperation(toolName, WRITE_OPERATIONS) ||
    (operation && WRITE_OPERATIONS.has(operation)) ||
    (mcpTargetPaths(input).length > 0 && mcpHasContent(input)),
  );
}

function patchTargetPaths(source: unknown): { targets: string[]; deleted: string[] } {
  if (typeof source !== "string") return { targets: [], deleted: [] };
  const targets: string[] = [];
  const deleted: string[] = [];
  let current: string | undefined;
  for (const line of source.slice(0, 64 * 1024).split("\n")) {
    const header = /^\*\*\*\s+(Add|Update|Delete)\s+File:\s+(.+)$/u.exec(line);
    if (header) {
      current = stringValue(header[2]?.trim().replace(/^['"]|['"]$/gu, ""));
      if (current) targets.push(current);
      if (header[1] === "Delete" && current) deleted.push(current);
      continue;
    }
    if (current && line.startsWith("*** Move to: ")) {
      const destination = stringValue(line.slice("*** Move to: ".length).trim().replace(/^['"]|['"]$/gu, ""));
      if (destination) {
        targets.push(destination);
        deleted.push(current);
      }
    }
  }
  return { targets: unique(targets), deleted: unique(deleted) };
}

function editPreGateInputs(input: Record<string, unknown>): Record<string, unknown>[] | undefined {
  if (!Array.isArray(input.edits)) return undefined;
  const direct = stringValue(input.path) ?? stringValue(input.file_path);
  const rows: Record<string, unknown>[] = [];
  for (const edit of input.edits) {
    if (!edit || typeof edit !== "object" || Array.isArray(edit)) continue;
    const record = edit as Record<string, unknown>;
    const path = stringValue(record.path) ?? direct;
    if (!path) continue;
    const text = ["new_string", "newString", "new_source", "newSource", "content"]
      .map(key => record[key])
      .find(value => typeof value === "string");
    rows.push({ file_path: path, new_string: typeof text === "string" ? text : "" });
  }
  return rows.length > 0 ? rows : undefined;
}

function mutationTargets(
  toolName: string,
  input: Record<string, unknown>,
  resolveTargets?: TargetResolver,
): { targets: string[]; deleted: string[] } {
  const normalized = normalizeArgs(input);
  const targets: string[] = [];
  const deleted: string[] = [];
  const direct = stringValue(normalized.file_path);
  if (direct) targets.push(direct);
  const lower = toolName.toLowerCase();
  if (lower === "apply_patch") {
    for (const key of ["input", "patch", "command"]) {
      const patch = patchTargetPaths(normalized[key]);
      targets.push(...patch.targets);
      deleted.push(...patch.deleted);
    }
  }
  if (lower === "edit" || lower === "multiedit") {
    const edits = normalized.edits;
    if (Array.isArray(edits)) {
      for (const edit of edits) {
        if (!edit || typeof edit !== "object" || Array.isArray(edit)) continue;
        const record = edit as Record<string, unknown>;
        const editPath = stringValue(record.path);
        if (editPath) targets.push(editPath);
        const op = stringValue(record.op)?.toLowerCase();
        const rename = stringValue(record.rename);
        if (rename) {
          targets.push(rename);
          if (direct) deleted.push(direct);
        }
        if (op === "delete" && direct) deleted.push(direct);
      }
    }
  }
  if (lower === "bash" && resolveTargets) targets.push(...resolveTargets(toolName, normalized));
  if (lower.startsWith("mcp__")) {
    targets.push(...mcpTargetPaths(input));
    if (DELETE_OPERATIONS.has(operationValue(input) ?? "") || mcpNameHasOperation(toolName, DELETE_OPERATIONS)) {
      deleted.push(...mcpTargetPaths(input));
    }
  }
  return { targets: unique(targets), deleted: unique(deleted) };
}

function isHostReportWrite(toolName: string, input: Record<string, unknown>): boolean {
  return toolName === "write" &&
    input.path === "xd://report_issue" &&
    typeof input.content === "string" &&
    REPORT_PATH_ALIASES.every(key => !Object.prototype.hasOwnProperty.call(input, key));
}

export function mutationKind(toolName: string, input: Record<string, unknown> = {}): MutationKind {
  if (isHostReportWrite(toolName, input)) return "host-report";
  const lower = toolName.toLowerCase();
  if (READ_TOOLS.has(lower)) return "read";
  if (lower === "context_notes") return Object.prototype.hasOwnProperty.call(input, "text") ? "unknown-write" : "read";
  if (lower === "bash") return "bash";
  if (lower === "write" || lower === "edit" || lower === "multiedit" || lower === "apply_patch") return "write";
  if (lower === "notebookedit" || lower === "notebook" || lower === "write_notebook") {
    return NOTEBOOK_READ_OPERATIONS.has(operationValue(input) ?? "") ? "read" : "notebook";
  }
  if (lower === "eval") {
    const language = stringValue(input.language)?.toLowerCase();
    if (language === "py" || language === "python") return "python";
    if (language === "js" || language === "javascript") return isToolDispatch(input.code) ? "other" : "unknown-write";
    return "unknown-write";
  }
  if (lower === "python") return "python";
  if (lower === "debug") return DEBUG_READ_ACTIONS.has(operationValue(input) ?? "") ? "other" : "unknown-write";
  if (lower === "lsp") return LSP_READ_ACTIONS.has(operationValue(input) ?? "") ? "other" : "unknown-write";
  if (lower.startsWith("mcp__")) {
    if (Object.prototype.hasOwnProperty.call(input, "command")) return "unknown-write";
    return mcpIsMutation(toolName, input) ? "mcp" : "other";
  }
  if (Object.prototype.hasOwnProperty.call(input, "command")) return "unknown-write";
  return SAFE_NON_MUTATING_TOOLS.has(lower) ? "other" : "unknown-write";
}

function directInput(input: Record<string, unknown>): Record<string, unknown> {
  return normalizeArgs(input);
}

export function adaptPythonEvent(event: { code: string; cwd?: string }): AdaptedTool {
  return pythonInput(event.code);
}

export function adaptToolCall(event: OmpToolEvent, resolveTargets?: TargetResolver): AdaptedTool {
  const input = event.input ?? {};
  const kind = mutationKind(event.toolName, input);
  if (kind === "python" && ["eval", "python"].includes(event.toolName.toLowerCase())) {
    return pythonInput(stringValue(input.code) ?? "");
  }
  const hookToolName = DIRECT_TOOL_NAMES[event.toolName.toLowerCase()] ?? event.toolName;
  if (kind === "host-report") {
    return { kind, hookToolName, input: { ...input }, requiresTarget: false };
  }
  if (kind === "unknown-write") {
    const language = stringValue(input.language)?.toLowerCase();
    const reason = event.toolName.toLowerCase() === "eval" && (language === "js" || language === "javascript")
      ? UNSUPPORTED_JAVASCRIPT_REASON : UNKNOWN_WRITE_REASON;
    return { kind, hookToolName, input: { ...input }, requiresTarget: true, reason };
  }
  const normalized = directInput(input);
  const targets = mutationTargets(event.toolName, input, resolveTargets);
  const preGateInputs = editPreGateInputs(input);
  return {
    kind,
    hookToolName,
    input: normalized,
    requiresTarget: kind === "write" || kind === "notebook" || kind === "mcp",
    ...(preGateInputs ? { preGateInputs } : {}),
    ...(kind === "write" || kind === "notebook" || kind === "bash" || kind === "mcp"
      ? (targets.targets.length > 0 ? { targetPaths: targets.targets } : {})
      : {}),
    ...(kind === "write" || kind === "notebook" || kind === "mcp"
      ? (targets.deleted.length > 0 ? { deletedTargetPaths: targets.deleted } : {})
      : {}),
  };
}

export function adaptToolResult(event: OmpToolEvent, resolveTargets?: TargetResolver): AdaptedTool {
  return adaptToolCall(event, resolveTargets);
}
