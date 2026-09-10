import { normalizeArgs } from "./watcher";

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
export type MutationKind = "read" | "write" | "bash" | "notebook" | "python" | "unknown-write" | "other";

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
  reason?: string;
};

const UNKNOWN_WRITE_REASON =
  "agent-discipline-watcher could not classify this OMP tool as a safe mutation.";

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

function mutationTargets(toolName: string, input: Record<string, unknown>): { targets: string[]; deleted: string[] } {
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
  return { targets: unique(targets), deleted: unique(deleted) };
}

function declaresWrite(input: Record<string, unknown>): boolean {
  const operation = operationValue(input);
  if (operation && WRITE_OPERATIONS.has(operation)) return true;
  const hasTarget = ["path", "file_path", "filePath", "notebook_path", "notebookPath"].some(key => key in input);
  const hasBody = ["content", "new_string", "newString", "new_source", "newSource", "patch"].some(key => key in input);
  return hasTarget && hasBody;
}

export function mutationKind(toolName: string, input: Record<string, unknown> = {}): MutationKind {
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
    if (language === "js" || language === "javascript") return "unknown-write";
    return "unknown-write";
  }
  if (lower === "python") return "python";
  if (lower.startsWith("mcp__")) return "other";
  return declaresWrite(input) ? "unknown-write" : "other";
}

function directInput(input: Record<string, unknown>): Record<string, unknown> {
  return normalizeArgs(input);
}

export function adaptPythonEvent(event: { code: string; cwd?: string }): AdaptedTool {
  return pythonInput(event.code);
}

export function adaptToolCall(event: OmpToolEvent): AdaptedTool {
  const input = event.input ?? {};
  const kind = mutationKind(event.toolName, input);
  if (kind === "python" && ["eval", "python"].includes(event.toolName.toLowerCase())) {
    return pythonInput(stringValue(input.code) ?? "");
  }
  const hookToolName = DIRECT_TOOL_NAMES[event.toolName.toLowerCase()] ?? event.toolName;
  if (kind === "unknown-write") {
    return { kind, hookToolName, input: { ...input }, requiresTarget: true, reason: UNKNOWN_WRITE_REASON };
  }
  const normalized = directInput(input);
  const targets = mutationTargets(event.toolName, input);
  return {
    kind,
    hookToolName,
    input: normalized,
    requiresTarget: kind === "write" || kind === "notebook",
    ...(kind === "write" || kind === "notebook"
      ? (targets.targets.length > 0 ? { targetPaths: targets.targets } : {})
      : {}),
    ...(kind === "write" || kind === "notebook"
      ? (targets.deleted.length > 0 ? { deletedTargetPaths: targets.deleted } : {})
      : {}),
  };
}

export function adaptToolResult(event: OmpToolEvent): AdaptedTool {
  return adaptToolCall(event);
}
