import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { Buffer } from "node:buffer";
import { lstatSync, statSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import { sanitizeDisplay } from "./adw-config";
import { hashlineEdits, hashlinePatchSource, type HashlineEdit } from "./hashline";
import { VerificationLedger } from "./lifecycle";
import { WorkspaceObserver } from "./workspace-observer";
import type { OmpReviewContext, OmpReviewRun } from "./omp-review";
import { runReviewBridge, validatedTargetPaths, type ReviewBridge } from "./omp-review-bridge";
import {
  adaptPythonEvent,
  adaptToolCall,
  adaptToolResult,
  type AdaptedTool,
  type TargetResolver,
} from "./tool-adapter";
import {
  blockReason,
  canonicalPath,
  feedbackMessage,
  isPostScanTool,
  isPreGateTool,
  postToolPaths,
  watcherPayload,
  type WatcherResult,
  type WatcherRun,
} from "./watcher";

type ExtensionContext = OmpReviewContext;

type ToolCallEvent = {
  toolName: string;
  toolCallId?: string;
  input: Record<string, unknown>;
};

type ToolResultEvent = {
  toolName: string;
  toolCallId?: string;
  input: Record<string, unknown>;
  content: Array<{ type: string; text?: string }>;
  details?: unknown;
  isError?: boolean;
};

type SessionStopEvent = {
  stop_hook_active?: boolean;
  stopHookActive?: boolean;
  signal?: AbortSignal;
};

type SessionStopResult =
  | { decision: "block"; reason: string }
  | { continue: true; additionalContext?: string }
  | undefined;

type UserPythonEvent = {
  code: string;
  cwd: string;
};

const UNRESOLVED_EDIT_SCAN =
  "agent-discipline-watcher could not resolve the edited file path from this edit result. Re-verify the touched file before finishing.";
const UNDECODABLE_EDIT =
  "agent-discipline-watcher could not decode this edit patch, so nothing was scanned. Split it into fewer sections and retry.";
const UNRESOLVED_EDIT_TARGET =
  "agent-discipline-watcher could not resolve a valid edit target for scanning, so nothing was scanned.";
const MAX_CACHED_BASH_TARGETS = 256;
const UNVERIFIED_POST_TOOL = "PostToolUse watcher could not verify the completed tool result";
const UNRESOLVED_NATIVE_EDIT =
  "OMP edit expects hashline input beginning with [path#hash] and anchored operations. Read the file for its current hashline, then use PUT, INS, or DEL.";

function sessionId(ctx: ExtensionContext): string {
  return ctx.sessionManager.getSessionId();
}

function stopHookRetryActive(event: SessionStopEvent): boolean {
  return Boolean(event.stop_hook_active ?? event.stopHookActive);
}

function appendNotice(
  content: Array<{ type: string; text?: string }>,
  message: string,
): Array<{ type: string; text?: string }> {
  const notice = `\n\n[agent-discipline-watcher]\n${sanitizeDisplay(message, 16 * 1024)}`;
  const updated = content.map(chunk => {
    if (chunk.type !== "text") return chunk;
    return { ...chunk, text: `${chunk.text ?? ""}${notice}` };
  });
  if (!updated.some(chunk => chunk.type === "text")) updated.push({ type: "text", text: notice.trimStart() });
  return updated;
}

function toolFailureText(content: Array<{ type: string; text?: string }>): string {
  const text = content
    .filter(chunk => chunk.type === "text" && typeof chunk.text === "string")
    .map(chunk => chunk.text ?? "")
    .join("\n");
  return sanitizeDisplay(text, 1024) || "tool result reported an error";
}

function eventFailurePayload(
  ctx: ExtensionContext,
  event: ToolResultEvent,
  adapted?: AdaptedTool,
): Record<string, unknown> {
  const payload = watcherPayload(
    ctx.cwd,
    sessionId(ctx),
    adapted?.hookToolName ?? event.toolName,
    adapted?.input ?? event.input,
    event.toolCallId,
  );
  payload.error = toolFailureText(event.content);
  payload.is_interrupt = false;
  payload.duration_ms = 0;
  return payload;
}

function payloadFilePath(payload: Record<string, unknown>): string | undefined {
  const input = payload.tool_input;
  if (!input || typeof input !== "object" || Array.isArray(input)) return undefined;
  const path = (input as Record<string, unknown>).file_path;
  return typeof path === "string" ? path : undefined;
}

function payloadTargets(payloads: readonly Record<string, unknown>[]): string[] {
  return [...new Set(payloads.map(payloadFilePath).filter((path): path is string => Boolean(path)))];
}

function pythonFailureResult(reason: string): Record<string, unknown> {
  const output = sanitizeDisplay(reason, 16 * 1024);
  const bytes = Buffer.byteLength(output, "utf8");
  return {
    output,
    exitCode: 1,
    cancelled: false,
    truncated: false,
    totalLines: 1,
    totalBytes: bytes,
    outputLines: 1,
    outputBytes: bytes,
    displayOutputs: [],
    stdinRequested: false,
  };
}

function addAdaptedTargets(paths: Set<string>, adapted: AdaptedTool, cwd: string): void {
  for (const rawPath of adapted.targetPaths ?? []) {
    const target = canonicalPath(rawPath, cwd);
    if (target !== undefined) paths.add(target);
  }
}

function adaptedTargets(adapted: AdaptedTool, cwd: string): string[] {
  const targets = new Set<string>();
  addAdaptedTargets(targets, adapted, cwd);
  return [...targets];
}

function adaptedDeletedTargets(adapted: AdaptedTool, cwd: string): string[] {
  const targets = new Set<string>();
  for (const rawPath of adapted.deletedTargetPaths ?? []) {
    const target = canonicalPath(rawPath, cwd);
    if (target !== undefined) targets.add(target);
  }
  return [...targets];
}

function mayContainWrittenContent(target: string): boolean {
  try {
    return statSync(target).isFile();
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== "ENOENT";
  }
}

function isMissingPath(target: string): boolean {
  try {
    lstatSync(target);
    return false;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "ENOENT";
  }
}

function bashWorkingDirectory(ctx: ExtensionContext, input: Record<string, unknown>): string {
  const raw = input.cwd;
  if (typeof raw !== "string" || !raw.trim() || raw.trim() === ".") return ctx.cwd;
  if (resolve(ctx.cwd, raw) === resolve(ctx.cwd)) return ctx.cwd;
  const target = canonicalPath(raw, ctx.cwd);
  if (target === undefined) throw new Error("Bash cwd is not a valid path");
  return target;
}

function adjustBashPayloadCwd(ctx: ExtensionContext, event: ToolCallEvent, payload: Record<string, unknown>): void {
  if (event.toolName.toLowerCase() !== "bash") return;
  payload.cwd = bashWorkingDirectory(ctx, event.input);
}

export function preGatePayloads(
  ctx: ExtensionContext,
  event: ToolCallEvent,
  sections: readonly HashlineEdit[],
  perTargetInputs: readonly Record<string, unknown>[] = [],
): Array<Record<string, unknown>> {
  if (sections.length === 0) {
    if (perTargetInputs.length > 0) {
      return perTargetInputs.map(input => watcherPayload(ctx.cwd, sessionId(ctx), event.toolName, input, event.toolCallId));
    }
    const payload = watcherPayload(ctx.cwd, sessionId(ctx), event.toolName, event.input, event.toolCallId);
    adjustBashPayloadCwd(ctx, event, payload);
    return [payload];
  }
  return sections.map(section => {
    const target = canonicalPath(section.path, ctx.cwd);
    if (target === undefined) throw new Error(UNRESOLVED_EDIT_TARGET);
    return watcherPayload(
      ctx.cwd,
      sessionId(ctx),
      event.toolName,
      { file_path: target, new_string: section.added },
      event.toolCallId,
    );
  });
}

type Lifecycle = {
  pi: ExtensionAPI;
  run: WatcherRun;
  review: OmpReviewRun;
  ledger: VerificationLedger;
  observer: WorkspaceObserver;
  resolveBashTargets: (ctx: ExtensionContext, event: ToolCallEvent | ToolResultEvent) => TargetResolver;
};

type ResultTurn = {
  state: Lifecycle;
  event: ToolResultEvent;
  ctx: ExtensionContext;
  session: string;
  adapted: AdaptedTool;
};

type WorkspaceChanges = ReturnType<WorkspaceObserver["collect"]>;

const TRACKED_MUTATIONS = ["write", "bash", "mcp", "notebook", "python"];

function bashTargetResolver(targetsBridge: ReviewBridge): Lifecycle["resolveBashTargets"] {
  const cache = new Map<string, readonly string[]>();
  const bridged = (ctx: ExtensionContext, input: Record<string, unknown>, toolCallId?: string): readonly string[] => {
    const paths = validatedTargetPaths(targetsBridge({
      operation: "targets",
      payload: watcherPayload(ctx.cwd, sessionId(ctx), "Bash", input, toolCallId),
    }));
    const cwd = bashWorkingDirectory(ctx, input);
    return paths.map(path => isAbsolute(path) || path.startsWith("~") ? path : resolve(cwd, path));
  };
  return (ctx, event) => (toolName, input) => {
    if (toolName.toLowerCase() !== "bash" || typeof input.command !== "string") return [];
    if (!event.toolCallId) return bridged(ctx, input);
    const key = JSON.stringify([sessionId(ctx), event.toolCallId, input.command, input.cwd ?? null]);
    const cached = cache.get(key);
    if (cached) return cached;
    const resolved = bridged(ctx, input, event.toolCallId);
    cache.set(key, resolved);
    if (cache.size > MAX_CACHED_BASH_TARGETS) cache.delete(cache.keys().next().value ?? "");
    return resolved;
  };
}

async function sendContext(pi: ExtensionAPI, message: string): Promise<void> {
  await pi.sendMessage(
    {
      customType: "agent-discipline-watcher.context",
      content: sanitizeDisplay(message, 16 * 1024),
      display: false,
      attribution: "agent-discipline-watcher",
    },
    { deliverAs: "nextTurn", triggerTurn: false },
  );
}

async function onSessionStart(state: Lifecycle, ctx: ExtensionContext): Promise<void> {
  state.ledger.resetSession(sessionId(ctx));
  state.observer.reset(sessionId(ctx));
  try {
    const result = state.run("SessionStart", watcherPayload(ctx.cwd, sessionId(ctx)));
    const message = feedbackMessage(result) ?? blockReason(result);
    if (message) await sendContext(state.pi, message);
  } catch (error) {
    await sendContext(state.pi, error instanceof Error ? error.message : "SessionStart watcher failed");
  }
}

function rejectCall(state: Lifecycle, session: string, event: ToolCallEvent, reason: string) {
  if (event.toolCallId) state.ledger.rejectTool(session, event.toolCallId);
  return { block: true as const, reason };
}

function errorReason(error: unknown, fallback: string): string {
  return sanitizeDisplay(error instanceof Error ? error.message : fallback, 16 * 1024);
}

function gateToolCall(state: Lifecycle, event: ToolCallEvent, ctx: ExtensionContext, adapted: AdaptedTool) {
  const session = sessionId(ctx);
  const gateEvent = { ...event, toolName: adapted.hookToolName, input: adapted.input };
  const sections = hashlineEdits(hashlinePatchSource(gateEvent.input));
  if (sections === undefined) return rejectCall(state, session, event, UNDECODABLE_EDIT);
  const payloads = preGatePayloads(ctx, gateEvent, sections, adapted.preGateInputs);
  const targets = [...payloadTargets(payloads), ...adaptedTargets(adapted, ctx.cwd)];
  if (adapted.requiresTarget && targets.length === 0) {
    return rejectCall(state, session, event, adapted.hookToolName === "Edit" ? UNRESOLVED_NATIVE_EDIT : UNRESOLVED_EDIT_TARGET);
  }
  for (const payload of payloads) {
    const reason = blockReason(state.run("PreToolUse", payload));
    if (reason) return rejectCall(state, session, event, sanitizeDisplay(reason, 16 * 1024));
  }
  if (TRACKED_MUTATIONS.includes(adapted.kind) && event.toolCallId) {
    state.ledger.acceptTool(session, event.toolCallId, targets, adaptedDeletedTargets(adapted, ctx.cwd));
  }
  return undefined;
}

async function onToolCall(state: Lifecycle, event: ToolCallEvent, ctx: ExtensionContext) {
  let adapted: AdaptedTool;
  try {
    adapted = adaptToolCall(event, state.resolveBashTargets(ctx, event));
  } catch (error) {
    return rejectCall(state, sessionId(ctx), event, errorReason(error, "agent-discipline-watcher could not decode this OMP tool call"));
  }
  if (adapted.kind === "observed") {
    state.observer.begin(sessionId(ctx), ctx.cwd);
    return undefined;
  }
  if (adapted.kind === "host-report") return undefined;
  if (!isPreGateTool(event.toolName) && !TRACKED_MUTATIONS.includes(adapted.kind)) return undefined;
  const session = sessionId(ctx);
  try {
    return gateToolCall(state, event, ctx, adapted);
  } catch (error) {
    return rejectCall(state, session, event, errorReason(error, "agent-discipline-watcher PreToolUse failed"));
  }
}

async function onUserPython(state: Lifecycle, event: UserPythonEvent, ctx: ExtensionContext) {
  const adapted = adaptPythonEvent(event);
  try {
    const result = state.run("PreToolUse", watcherPayload(ctx.cwd, sessionId(ctx), adapted.hookToolName, adapted.input));
    const reason = blockReason(result);
    if (reason) return { result: pythonFailureResult(reason) };
    return undefined;
  } catch (error) {
    return { result: pythonFailureResult(error instanceof Error ? error.message : "agent-discipline-watcher Python gate failed") };
  }
}

function adaptResult(state: Lifecycle, event: ToolResultEvent, ctx: ExtensionContext): AdaptedTool {
  try {
    return adaptToolResult(event, state.resolveBashTargets(ctx, event));
  } catch {
    return { kind: "observed", hookToolName: event.toolName, input: event.input, requiresTarget: false };
  }
}

function acceptedCall(turn: ResultTurn): boolean {
  return Boolean(turn.event.toolCallId && turn.state.ledger.acceptedTool(turn.session, turn.event.toolCallId));
}

function scansResult(turn: ResultTurn): boolean {
  const { event, adapted } = turn;
  if (adapted.kind === "host-report" && !acceptedCall(turn)) return false;
  const acceptedMcpResult = event.toolName.toLowerCase().startsWith("mcp__") && acceptedCall(turn);
  return adapted.kind === "observed" || isPostScanTool(event.toolName) || TRACKED_MUTATIONS.includes(adapted.kind) || acceptedMcpResult;
}

function resultPaths(turn: ResultTurn, changes: WorkspaceChanges): Set<string> {
  const { state, event, ctx, session, adapted } = turn;
  const observed = adapted.kind === "observed";
  const paths = new Set<string>();
  try {
    if (!observed) for (const path of postToolPaths(adapted.input, event.details, event.content, ctx.cwd)) paths.add(path);
  } catch {
    paths.clear();
  }
  if (!observed) addAdaptedTargets(paths, adapted, ctx.cwd);
  for (const path of changes.changed) paths.add(path);
  if (event.toolCallId) {
    for (const path of state.ledger.acceptedTargets(session, event.toolCallId)) paths.add(path);
  }
  return paths;
}

function noticeResult(event: ToolResultEvent, messages: readonly string[]) {
  const message = [...new Set(messages)].join("\n\n");
  return message ? { content: appendNotice(event.content, message) } : undefined;
}

function failedResult(turn: ResultTurn, paths: ReadonlySet<string>) {
  const { state, event, ctx, session, adapted } = turn;
  let result: WatcherResult;
  try {
    result = state.run("PostToolUseFailure", eventFailurePayload(ctx, event, adapted));
  } catch {
    result = { decision: "block", reason: "PostToolUseFailure watcher failed" };
  }
  const message = feedbackMessage(result);
  const failedTargets = new Set(paths);
  const accepted = event.toolCallId ? state.ledger.acceptedTool(session, event.toolCallId) : false;
  const rejected = event.toolCallId ? state.ledger.rejectedTool(session, event.toolCallId) : false;
  if (!rejected && accepted && event.toolCallId) {
    for (const target of state.ledger.acceptedTargets(session, event.toolCallId)) failedTargets.add(target);
  }
  if (!rejected) {
    for (const target of failedTargets) if (mayContainWrittenContent(target)) state.ledger.markPending(session, target);
  }
  if (event.toolCallId) state.ledger.finishTool(session, event.toolCallId);
  return noticeResult(event, message ? [message] : []);
}

function unresolvedResult(turn: ResultTurn, changes: WorkspaceChanges) {
  const { state, event, session, adapted } = turn;
  if (!adapted.requiresTarget) {
    if (event.toolCallId) state.ledger.finishTool(session, event.toolCallId);
    return changes.notices.length ? { content: appendNotice(event.content, changes.notices.join("\n\n")) } : undefined;
  }
  state.ledger.markUnknown(session);
  if (event.toolCallId) state.ledger.finishTool(session, event.toolCallId);
  return { content: appendNotice(event.content, UNRESOLVED_EDIT_SCAN) };
}

async function scanResultPath(turn: ResultTurn, filePath: string, messages: string[]): Promise<void> {
  const { state, event, ctx, session, adapted } = turn;
  try {
    state.observer.acknowledge(session, filePath);
    const tool = adapted.kind === "observed" ? "Write" : adapted.hookToolName;
    const result = state.run("PostToolUse", watcherPayload(ctx.cwd, session, tool, { file_path: filePath }, event.toolCallId));
    const postReason = blockReason(result);
    if (result.decision === "block" || postReason) {
      const reason = postReason ? `${UNVERIFIED_POST_TOOL}: ${sanitizeDisplay(postReason, 16 * 1024)}` : `${UNVERIFIED_POST_TOOL}.`;
      state.ledger.markPending(session, filePath, reason);
      messages.push(reason);
      return;
    }
    const message = feedbackMessage(result);
    if (message) messages.push(message);
    const reviewed = await state.review(ctx, watcherPayload(ctx.cwd, session, tool, { file_path: filePath }, event.toolCallId));
    const reviewReason = blockReason(reviewed);
    if (reviewed.decision === "block" || reviewReason) {
      const reason = reviewReason || "OMP review could not verify the completed tool result.";
      state.ledger.markPending(session, filePath, reason);
      messages.push(reason);
      return;
    }
    const reviewMessage = feedbackMessage(reviewed);
    if (reviewMessage) messages.push(reviewMessage);
    state.ledger.clearTarget(session, filePath);
  } catch {
    state.ledger.markPending(session, filePath);
    messages.push("PostToolUse watcher failed. Treat the result as unscanned.");
  }
}

async function onToolResult(state: Lifecycle, event: ToolResultEvent, ctx: ExtensionContext) {
  const adapted = adaptResult(state, event, ctx);
  const session = sessionId(ctx);
  const turn: ResultTurn = { state, event, ctx, session, adapted };
  const observed = adapted.kind === "observed";
  const changes: WorkspaceChanges = observed ? state.observer.collect(session) : { changed: [], deleted: [], notices: [] };
  for (const path of changes.deleted) if (isMissingPath(path)) state.ledger.clearTarget(session, path);
  if (!scansResult(turn)) return undefined;
  const paths = resultPaths(turn, changes);
  const deletedTargets = new Set(event.toolCallId ? state.ledger.acceptedDeletedTargets(session, event.toolCallId) : []);
  if (event.isError && !observed) return failedResult(turn, paths);
  if (paths.size === 0) return unresolvedResult(turn, changes);
  const messages: string[] = [...changes.notices];
  for (const filePath of paths) {
    if (deletedTargets.has(filePath) && isMissingPath(filePath)) {
      state.ledger.clearTarget(session, filePath);
      continue;
    }
    await scanResultPath(turn, filePath, messages);
  }
  if (event.toolCallId) state.ledger.finishTool(session, event.toolCallId);
  return noticeResult(event, messages);
}

async function recoverPending(state: Lifecycle, event: SessionStopEvent, ctx: ExtensionContext): Promise<string[]> {
  const session = sessionId(ctx);
  const messages: string[] = [];
  for (const target of state.ledger.pendingTargets(session)) {
    if (target === VerificationLedger.UNKNOWN_TARGET) continue;
    try {
      const post = state.run("PostToolUse", watcherPayload(ctx.cwd, session, "Write", { file_path: target }));
      if (post.decision === "block" || blockReason(post)) continue;
      const reviewed = await state.review(ctx, watcherPayload(ctx.cwd, session, "Write", { file_path: target }), event.signal);
      const reason = blockReason(reviewed);
      if (reviewed.decision === "block" || reason) {
        state.ledger.markPending(session, target, reason || "OMP review could not verify this file.");
        continue;
      }
      const feedback = feedbackMessage(reviewed) ?? feedbackMessage(post);
      if (feedback) messages.push(feedback);
      state.ledger.clearTarget(session, target);
    } catch {
      continue;
    }
  }
  return messages;
}

function stopVerdict(state: Lifecycle, event: SessionStopEvent, ctx: ExtensionContext, recoveryMessages: readonly string[]): SessionStopResult {
  try {
    const payload = watcherPayload(ctx.cwd, sessionId(ctx));
    if (stopHookRetryActive(event)) payload.stop_hook_active = true;
    const result = state.run("Stop", payload);
    const stopReason = blockReason(result);
    if (stopReason) {
      return { decision: "block", reason: sanitizeDisplay(stopReason, 16 * 1024) };
    }
    const additionalContext = feedbackMessage(result);
    const context = [...new Set([...recoveryMessages, additionalContext].filter((message): message is string => Boolean(message)))].join("\n\n");
    return context ? { continue: true, additionalContext: sanitizeDisplay(context, 16 * 1024) } : undefined;
  } catch (error) {
    return { decision: "block", reason: sanitizeDisplay(error instanceof Error ? error.message : "Stop watcher failed", 16 * 1024) };
  }
}

async function onSessionStop(state: Lifecycle, event: SessionStopEvent, ctx: ExtensionContext): Promise<SessionStopResult> {
  const session = sessionId(ctx);
  const changes = state.observer.collect(session);
  for (const path of changes.deleted) if (isMissingPath(path)) state.ledger.clearTarget(session, path);
  for (const path of changes.changed) state.ledger.markPending(session, path);
  const recoveryMessages = [...changes.notices, ...(await recoverPending(state, event, ctx))];
  if (state.ledger.hasPending(session)) {
    return {
      decision: "block",
      reason: sanitizeDisplay(state.ledger.pendingReasons(session).join("\n\n") || "agent-discipline-watcher could not verify every mutating tool result. Re-verify the touched file before stopping.", 16 * 1024),
    };
  }
  return stopVerdict(state, event, ctx, recoveryMessages);
}

export function registerLifecycleHandlers(
  pi: ExtensionAPI,
  run: WatcherRun,
  review: OmpReviewRun,
  targetsBridge: ReviewBridge = runReviewBridge,
): void {
  const state: Lifecycle = {
    pi, run, review,
    ledger: new VerificationLedger(),
    observer: new WorkspaceObserver(),
    resolveBashTargets: bashTargetResolver(targetsBridge),
  };
  pi.on("session_start", async (_event, ctx: ExtensionContext) => onSessionStart(state, ctx));
  pi.on("tool_call", async (event: ToolCallEvent, ctx: ExtensionContext) => onToolCall(state, event, ctx));
  pi.on("user_python", async (event: UserPythonEvent, ctx: ExtensionContext) => onUserPython(state, event, ctx));
  pi.on("tool_result", async (event: ToolResultEvent, ctx: ExtensionContext) => onToolResult(state, event, ctx));
  pi.on("session_stop", async (event: SessionStopEvent, ctx: ExtensionContext) => onSessionStop(state, event, ctx));
}
