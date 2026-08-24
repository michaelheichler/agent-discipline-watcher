import { execFileSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

export type WatcherEvent =
  | "SessionStart"
  | "PreToolUse"
  | "PostToolUse"
  | "Stop";

export type WatcherResult = {
  decision?: string;
  reason?: string;
  systemMessage?: string;
  hookSpecificOutput?: {
    additionalContext?: string;
    permissionDecision?: string;
    permissionDecisionReason?: string;
  };
};

export type WatcherRun = (
  event: WatcherEvent,
  payload: Record<string, unknown>,
) => WatcherResult;

const WRITE_TOOLS = new Set(["write", "edit", "multiedit", "notebookedit", "apply_patch"]);

const TOOL_NAME_MAP: Record<string, string> = {
  write: "Write",
  edit: "Edit",
  multiedit: "MultiEdit",
  notebookedit: "NotebookEdit",
  apply_patch: "apply_patch",
  bash: "Bash",
};

export function hookToolName(toolName: string): string {
  if (toolName.startsWith("mcp__")) {
    return toolName;
  }
  const mapped = TOOL_NAME_MAP[toolName.toLowerCase()];
  return mapped ?? toolName;
}

export function isPostScanTool(toolName: string): boolean {
  const lower = toolName.toLowerCase();
  return WRITE_TOOLS.has(lower) || lower === "bash";
}

export function isPreGateTool(toolName: string): boolean {
  const lower = toolName.toLowerCase();
  return lower === "write" || lower === "bash";
}


export function hashlinePaths(patch: string): string[] {
  const paths = new Set<string>();
  const headerRe = /^\[([^#\]]+)#[^\]]+\]/gm;
  const moveRe = /^MV\s+(.+)$/gm;
  for (const match of patch.matchAll(headerRe)) {
    const path = match[1]?.trim();
    if (path) {
      paths.add(path);
    }
  }
  for (const match of patch.matchAll(moveRe)) {
    const path = match[1]?.trim();
    if (path) {
      paths.add(path);
    }
  }
  return [...paths];
}

export function isPlainFilePath(path: string): boolean {
  if (!path || path.includes("://")) {
    return false;
  }
  if (path.includes(":") && !path.startsWith("/")) {
    return false;
  }
  return true;
}

function resultText(content?: Array<{ type: string; text?: string }>): string {
  if (!content) {
    return "";
  }
  return content
    .filter((chunk) => chunk.type === "text" && typeof chunk.text === "string")
    .map((chunk) => chunk.text ?? "")
    .join("\n");
}

export function postToolPaths(
  input: Record<string, unknown> | undefined,
  details?: unknown,
  content?: Array<{ type: string; text?: string }>,
): string[] {
  const paths = new Set<string>();
  const normalized = normalizeArgs(input);
  const direct = String(normalized.file_path ?? normalized.path ?? "").trim();
  if (direct) {
    paths.add(direct);
  }
  if (details && typeof details === "object" && "resolvedPath" in details) {
    const resolved = String((details as { resolvedPath?: unknown }).resolvedPath ?? "").trim();
    if (resolved) {
      paths.add(resolved);
    }
  }
  const patch = typeof normalized.input === "string" ? normalized.input : "";
  for (const path of hashlinePaths(patch)) {
    paths.add(path);
  }
  for (const path of hashlinePaths(resultText(content))) {
    paths.add(path);
  }
  return [...paths];
}

export function normalizeArgs(args: Record<string, unknown> | undefined): Record<string, unknown> {
  if (!args) {
    return {};
  }
  const normalized: Record<string, unknown> = { ...args };
  const mappings: Array<[string, string]> = [
    ["filePath", "file_path"],
    ["newString", "new_string"],
    ["oldString", "old_string"],
    ["path", "file_path"],
  ];
  for (const [source, destination] of mappings) {
    if (source in normalized && !(destination in normalized)) {
      normalized[destination] = normalized[source];
      delete normalized[source];
    }
  }
  return normalized;
}

export function resolveRunner(
  environment: Record<string, string | undefined> = process.env,
  home: string = homedir(),
): string {
  const override = environment.AGENT_DISCIPLINE_WATCHER_HOME;
  const root = override || join(home, ".agents", "skills", "agent-discipline-watcher");
  return join(root, "hooks", "run.sh");
}

export function runWatcher(
  event: WatcherEvent,
  payload: Record<string, unknown>,
  runner: string = resolveRunner(),
): WatcherResult {
  try {
    const output = execFileSync(runner, [event], {
      encoding: "utf-8",
      input: JSON.stringify(payload),
      maxBuffer: 1024 * 1024,
    }).trim();
    return output ? (JSON.parse(output) as WatcherResult) : {};
  } catch (error) {
    const failure = error as {
      stderr?: string | Buffer;
      stdout?: string | Buffer;
      message?: string;
    };
    const stderr = String(failure.stderr ?? "").trim();
    const stdout = String(failure.stdout ?? "").trim();
    return {
      decision: "block",
      reason: stderr || stdout || failure.message || `${event} watcher failed`,
    };
  }
}

export function blockReason(result: WatcherResult): string | undefined {
  if (result.decision === "block") {
    return result.reason || "agent-discipline-watcher blocked the operation";
  }
  const specific = result.hookSpecificOutput;
  if (specific?.permissionDecision === "deny") {
    return specific.permissionDecisionReason || result.reason || "agent-discipline-watcher blocked the operation";
  }
  return undefined;
}

export function feedbackMessage(result: WatcherResult): string | undefined {
  const specific = result.hookSpecificOutput?.additionalContext;
  if (typeof specific === "string" && specific.trim()) {
    return specific;
  }
  const system = result.systemMessage;
  return typeof system === "string" && system.trim() ? system : undefined;
}

export function watcherPayload(
  cwd: string,
  sessionId: string,
  toolName?: string,
  toolInput?: Record<string, unknown>,
  toolUseId?: string,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    cwd,
    session_id: sessionId,
  };
  if (toolName) {
    payload.tool_name = hookToolName(toolName);
  }
  if (toolInput) {
    payload.tool_input = normalizeArgs(toolInput);
  }
  if (toolUseId) {
    payload.tool_use_id = toolUseId;
  }
  return payload;
}
