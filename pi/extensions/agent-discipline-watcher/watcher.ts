import { execFileSync } from "node:child_process";
import { existsSync, realpathSync } from "node:fs";
import { Buffer } from "node:buffer";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

const MAX_RUNNER_INPUT_BYTES = 1_000_000;
const MAX_RUNNER_OUTPUT_BYTES = 64 * 1024;
const RUNNER_TIMEOUT_MS = 30_000;
const MAX_RESULT_CHUNKS = 64;
const MAX_RESULT_BYTES = 64 * 1024;
const MAX_RESULT_PATHS = 32;
const MAX_MESSAGE_BYTES = 16 * 1024;
const PATH_ALIASES = ["file_path", "filePath", "path", "notebook_path", "notebookPath"] as const;
const PATCH_ALIASES = ["patch", "command", "input"] as const;
const TEXT_ALIASES: Array<readonly [string, readonly string[]]> = [
  ["new_string", ["new_string", "newString", "newSource"]],
  ["old_string", ["old_string", "oldString"]],
];
const WATCHER_RESULT_KEYS: Record<string, true> = {
  decision: true,
  reason: true,
  systemMessage: true,
  hookSpecificOutput: true,
};
const SPECIFIC_RESULT_KEYS: Record<string, true> = {
  hookEventName: true,
  additionalContext: true,
  permissionDecision: true,
  permissionDecisionReason: true,
};

export type WatcherEvent =
  | "SessionStart"
  | "UserPromptSubmit"
  | "PreToolUse"
  | "PostToolUse"
  | "PostToolUseFailure"
  | "JudgeReview"
  | "SubagentStart"
  | "SubagentStop"
  | "Stop";

export type WatcherResult = {
  decision?: "block";
  reason?: string;
  systemMessage?: string;
  hookSpecificOutput?: {
    hookEventName?: string;
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


function safeText(value: string): string {
  return [...value]
    .filter((character) => {
      const code = character.codePointAt(0) ?? 0;
      return (code >= 0x20 && code !== 0x7f && !(code >= 0x80 && code <= 0x9f) && !(code >= 0x202a && code <= 0x202e));
    })
    .join("");
}
function clipUtf8(value: string, limit: number): string {
  const encoded = Buffer.from(value, "utf8");
  return encoded.length <= limit ? value : encoded.subarray(0, limit).toString("utf8");
}

function aliasValue(
  args: Record<string, unknown>,
  alias: string,
  label: string,
  trim = true,
): string | undefined {
  if (!Object.prototype.hasOwnProperty.call(args, alias)) {
    return undefined;
  }
  const value = args[alias];
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value !== "string") {
    throw new Error(`invalid ${label}`);
  }
  if (!trim) {
    return value;
  }
  const trimmed = value.trim();
  return trimmed || undefined;
}

function canonicalAlias(
  args: Record<string, unknown>,
  aliases: readonly string[],
  label: string,
  trim = true,
): string | undefined {
  let selected: string | undefined;
  for (const alias of aliases) {
    const value = aliasValue(args, alias, label, trim);
    if (value === undefined) {
      continue;
    }
    if (selected !== undefined && selected !== value) {
      throw new Error(`conflicting ${label} aliases`);
    }
    selected = value;
  }
  return selected;
}


function patchText(args: Record<string, unknown>): string {
  for (const alias of PATCH_ALIASES) {
    const value = args[alias];
    if (typeof value === "string") {
      return clipUtf8(value, MAX_RESULT_BYTES);
    }
  }
  return "";
}

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

export function isMutatingTool(toolName: string): boolean {
  return isPostScanTool(toolName);
}

export function isPreGateTool(toolName: string): boolean {
  const lower = toolName.toLowerCase();
  return isMutatingTool(lower) || lower.startsWith("mcp__");
}

function hasControlCharacter(value: string): boolean {
  return [...value].some((character) => {
    const code = character.codePointAt(0) ?? 0;
    return code < 0x20 || code === 0x7f;
  });
}

export function isPlainFilePath(path: string): boolean {
  return (
    typeof path === "string" &&
    path.length > 0 &&
    !hasControlCharacter(path) &&
    !path.includes("://") &&
    (!path.includes(":") || path.startsWith("/"))
  );
}

export function canonicalPath(rawPath: unknown, cwd?: string): string | undefined {
  if (typeof rawPath !== "string") {
    return undefined;
  }
  const path = rawPath.trim();
  if (!isPlainFilePath(path)) {
    return undefined;
  }
  if (!cwd || !cwd.trim()) {
    return path;
  }
  try {
    const root = resolve(cwd);
    const expanded = path === "~" ? homedir() : path.startsWith("~/") ? join(homedir(), path.slice(2)) : path;
    const target = resolve(root, expanded);
    const lexical = relative(root, target);
    if (!lexical || lexical === ".." || lexical.startsWith(`..${sep}`) || isAbsolute(lexical)) {
      return undefined;
    }
    let realRoot: string;
    try {
      realRoot = realpathSync(root);
    } catch {
      return undefined;
    }
    let realTarget: string;
    try {
      realTarget = realpathSync(target);
    } catch {
      let existing = dirname(target);
      while (true) {
        try {
          const realParent = realpathSync(existing);
          const suffix = relative(existing, target);
          realTarget = resolve(realParent, suffix);
          break;
        } catch {
          const parent = dirname(existing);
          if (parent === existing) return undefined;
          existing = parent;
        }
      }
    }
    const actual = relative(realRoot, realTarget);
    if (!actual || actual === ".." || actual.startsWith(`..${sep}`) || isAbsolute(actual)) {
      return undefined;
    }
    return target;
  } catch {
    return undefined;
  }
}

export function hashlinePaths(patch: string): string[] {
  if (typeof patch !== "string" || !patch) {
    return [];
  }
  const paths = new Set<string>();
  const bounded = clipUtf8(patch, MAX_RESULT_BYTES);
  const add = (rawPath: string | undefined) => {
    const path = rawPath?.trim().replace(/^["']|["']$/g, "");
    if (path && paths.size < MAX_RESULT_PATHS) {
      paths.add(path);
    }
  };
  const headerRe = /^\[([^#\]]+)#[^\]]+\]/gm;
  const moveRe = /^MV\s+(.+)$/gm;
  for (const match of bounded.matchAll(headerRe)) {
    add(match[1]);
    if (paths.size >= MAX_RESULT_PATHS) {
      break;
    }
  }
  if (paths.size < MAX_RESULT_PATHS) {
    for (const match of bounded.matchAll(moveRe)) {
      add(match[1]);
      if (paths.size >= MAX_RESULT_PATHS) {
        break;
      }
    }
  }
  return [...paths];
}

function resultText(content?: Array<{ type: string; text?: string }>): string {
  if (!Array.isArray(content)) {
    return "";
  }
  let result = "";
  for (let index = 0; index < Math.min(content.length, MAX_RESULT_CHUNKS); index += 1) {
    const chunk = content[index];
    if (!chunk || typeof chunk !== "object" || chunk.type !== "text" || typeof chunk.text !== "string") {
      continue;
    }
    const separator = result ? "\n" : "";
    const remaining = MAX_RESULT_BYTES - Buffer.byteLength(result, "utf8") - Buffer.byteLength(separator, "utf8");
    if (remaining <= 0) {
      break;
    }
    result += separator + clipUtf8(chunk.text, remaining);
  }
  return result;
}

function addCanonicalPath(
  paths: Set<string>,
  rawPath: unknown,
  cwd: string | undefined,
): string | undefined {
  const path = canonicalPath(rawPath, cwd);
  if (path !== undefined && paths.size < MAX_RESULT_PATHS) {
    paths.add(path);
  }
  return path;
}

export function postToolPaths(
  input: Record<string, unknown> | undefined,
  details?: unknown,
  content?: Array<{ type: string; text?: string }>,
  cwd?: string,
): string[] {
  const normalized = normalizeArgs(input);
  const inputPaths = new Set<string>();
  const paths = new Set<string>();
  const direct = normalized.file_path;
  const directPath = addCanonicalPath(inputPaths, direct, cwd);


  if (directPath !== undefined) {
    paths.add(directPath);
  }

  for (const rawPath of hashlinePaths(patchText(normalized))) {
    const path = addCanonicalPath(inputPaths, rawPath, cwd);
    if (path !== undefined && paths.size < MAX_RESULT_PATHS) {
      paths.add(path);
    }
  }

  const trustedPaths = inputPaths;
  for (const rawPath of hashlinePaths(resultText(content))) {
    const path = canonicalPath(rawPath, cwd);
    if (path !== undefined && trustedPaths.has(path) && paths.size < MAX_RESULT_PATHS) {
      paths.add(path);
    }
  }
  return [...paths];
}

export function normalizeArgs(args: Record<string, unknown> | undefined): Record<string, unknown> {
  if (!args) {
    return {};
  }
  const normalized: Record<string, unknown> = { ...args };
  const target = canonicalAlias(normalized, PATH_ALIASES, "path");
  for (const alias of PATH_ALIASES) {
    delete normalized[alias];
  }
  if (target !== undefined) {
    normalized.file_path = target;
  }

  for (const [canonical, aliases] of TEXT_ALIASES) {
    const value = canonicalAlias(normalized, aliases, canonical, false);
    for (const alias of aliases) {
      delete normalized[alias];
    }
    if (value !== undefined) {
      normalized[canonical] = value;
    }
  }
  canonicalAlias(normalized, PATCH_ALIASES, "patch", false);
  return normalized;
}

const LEGACY_RUNNER_ROOT = [".agents", "skills", "agent-discipline-watcher"];
const SIBLING_RUNNER = ["..", "..", "..", "hooks", "run.sh"];

export function resolveRunner(
  environment: Record<string, string | undefined> = process.env,
  home: string = homedir(),
  exists: (path: string) => boolean = existsSync,
  self: string = import.meta.dir,
): string {
  const override = environment.AGENT_DISCIPLINE_WATCHER_HOME;
  if (override) return join(override, "hooks", "run.sh");
  const beside = resolve(self, ...SIBLING_RUNNER);
  if (exists(beside)) return beside;
  const installed = join(home, ".adw", "install", "agent-discipline-watcher", "hooks", "run.sh");
  if (exists(installed)) return installed;
  return join(home, ...LEGACY_RUNNER_ROOT, "hooks", "run.sh");
}

function validatedToolInput(
  toolInput: Record<string, unknown>,
  cwd: string,
): Record<string, unknown> {
  const normalized = normalizeArgs(toolInput);
  if (normalized.file_path !== undefined) {
    const target = canonicalPath(normalized.file_path, cwd);
    if (target === undefined) {
      throw new Error("tool target is invalid or outside the session cwd");
    }
    normalized.file_path = target;
  }
  return normalized;
}

function validatedWatcherResult(value: unknown): WatcherResult | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  if (Object.keys(record).some((key) => !WATCHER_RESULT_KEYS[key])) {
    return undefined;
  }
  const result: WatcherResult = {};
  if ("decision" in record) {
    if (record.decision !== "block") {
      return undefined;
    }
    result.decision = "block";
  }
  if ("reason" in record) {
    if (typeof record.reason !== "string") {
      return undefined;
    }
    result.reason = clipUtf8(safeText(record.reason), MAX_MESSAGE_BYTES);
  }
  if ("systemMessage" in record) {
    if (typeof record.systemMessage !== "string") {
      return undefined;
    }
    result.systemMessage = clipUtf8(safeText(record.systemMessage), MAX_MESSAGE_BYTES);
  }
  if ("hookSpecificOutput" in record) {
    const rawSpecific = record.hookSpecificOutput;
    if (!rawSpecific || typeof rawSpecific !== "object" || Array.isArray(rawSpecific)) {
      return undefined;
    }
    const specificRecord = rawSpecific as Record<string, unknown>;
    if (Object.keys(specificRecord).some((key) => !SPECIFIC_RESULT_KEYS[key])) {
      return undefined;
    }
    const specific: NonNullable<WatcherResult["hookSpecificOutput"]> = {};
    for (const key of ["hookEventName", "additionalContext", "permissionDecision", "permissionDecisionReason"] as const) {
      if (key in specificRecord) {
        if (typeof specificRecord[key] !== "string") {
          return undefined;
        }
        specific[key] = clipUtf8(safeText(specificRecord[key]), MAX_MESSAGE_BYTES);
      }
    }
    result.hookSpecificOutput = specific;
  }
  return result;
}

export function runWatcher(
  event: WatcherEvent,
  payload: Record<string, unknown>,
  runner: string = resolveRunner(),
): WatcherResult {
  try {
    const serialized = JSON.stringify(payload);
    if (typeof serialized !== "string" || Buffer.byteLength(serialized, "utf8") > MAX_RUNNER_INPUT_BYTES) {
      return {
        decision: "block",
        reason: `${event} watcher input exceeded its size limit`,
      };
    }
    const output = execFileSync(runner, [event], {
      encoding: "utf-8",
      input: serialized,
      maxBuffer: MAX_RUNNER_OUTPUT_BYTES,
      timeout: RUNNER_TIMEOUT_MS,
    }).trim();
    if (!output) {
      return {
        decision: "block",
        reason: `${event} watcher returned no response`,
      };
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(output);
    } catch {
      return {
        decision: "block",
        reason: `${event} watcher returned malformed JSON`,
      };
    }
    return (
      validatedWatcherResult(parsed) ?? {
        decision: "block",
        reason: `${event} watcher returned malformed output`,
      }
    );
  } catch (error) {
    const failure = error as {
      stderr?: string | Buffer;
      stdout?: string | Buffer;
      message?: string;
    };
    const stderr = String(failure.stderr ?? "").trim();
    const stdout = String(failure.stdout ?? "").trim();
    const reason = stderr || stdout || failure.message || `${event} watcher failed`;
    return {
      decision: "block",
      reason: clipUtf8(reason, MAX_MESSAGE_BYTES),
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
    return clipUtf8(specific, MAX_MESSAGE_BYTES);
  }
  const system = result.systemMessage;
  return typeof system === "string" && system.trim() ? clipUtf8(system, MAX_MESSAGE_BYTES) : undefined;
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
    payload.tool_input = validatedToolInput(toolInput, cwd);
  }
  if (toolUseId) {
    payload.tool_use_id = toolUseId;
  }
  return payload;
}
