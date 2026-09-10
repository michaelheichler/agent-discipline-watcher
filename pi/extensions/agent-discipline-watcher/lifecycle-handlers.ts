import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { Buffer } from "node:buffer";
import { lstatSync, statSync } from "node:fs";
import { sanitizeDisplay } from "./adw-config";
import { hashlineEdits, hashlinePatchSource, type HashlineEdit } from "./hashline";
import { VerificationLedger } from "./lifecycle";
import type { OmpReviewContext, OmpReviewRun } from "./omp-review";
import {
  adaptPythonEvent,
  adaptToolCall,
  adaptToolResult,
  type AdaptedTool,
} from "./tool-adapter";
import {
  blockReason,
  canonicalPath,
  feedbackMessage,
  isPostScanTool,
  isPreGateTool,
  postToolPaths,
  watcherPayload,
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
const UNKNOWN_OMP_WRITE =
  "agent-discipline-watcher could not classify this OMP tool as a safe mutation.";

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

export function preGatePayloads(
  ctx: ExtensionContext,
  event: ToolCallEvent,
  sections: readonly HashlineEdit[],
): Array<Record<string, unknown>> {
  if (sections.length === 0) {
    return [watcherPayload(ctx.cwd, sessionId(ctx), event.toolName, event.input, event.toolCallId)];
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

export function registerLifecycleHandlers(pi: ExtensionAPI, run: WatcherRun, review: OmpReviewRun): void {
  const ledger = new VerificationLedger();

  pi.on("session_start", async (_event, ctx: ExtensionContext) => {
    ledger.resetSession(sessionId(ctx));
    try {
      const result = run("SessionStart", watcherPayload(ctx.cwd, sessionId(ctx)));
      const message = feedbackMessage(result) ?? blockReason(result);
      if (message) {
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
    } catch (error) {
      await pi.sendMessage(
        {
          customType: "agent-discipline-watcher.context",
          content: sanitizeDisplay(error instanceof Error ? error.message : "SessionStart watcher failed", 16 * 1024),
          display: false,
          attribution: "agent-discipline-watcher",
        },
        { deliverAs: "nextTurn", triggerTurn: false },
      );
    }
  });

  pi.on("tool_call", async (event: ToolCallEvent, ctx: ExtensionContext) => {
    let adapted: AdaptedTool;
    try {
      adapted = adaptToolCall(event);
    } catch (error) {
      return {
        block: true,
        reason: sanitizeDisplay(error instanceof Error ? error.message : "agent-discipline-watcher could not decode this OMP tool call", 16 * 1024),
      };
    }
    if (adapted.kind === "unknown-write") return { block: true, reason: adapted.reason ?? UNKNOWN_OMP_WRITE };
    const preGateMutation = ["write", "bash", "notebook", "python"].includes(adapted.kind);
    if (!isPreGateTool(event.toolName) && !preGateMutation) return undefined;
    const session = sessionId(ctx);
    const trackedMutation = ["write", "bash", "notebook", "python"].includes(adapted.kind);
    try {
      const gateEvent = { ...event, toolName: adapted.hookToolName, input: adapted.input };
      const sections = hashlineEdits(hashlinePatchSource(gateEvent.input));
      if (sections === undefined) {
        if (trackedMutation && event.toolCallId) ledger.rejectTool(session, event.toolCallId);
        return { block: true, reason: UNDECODABLE_EDIT };
      }
      const payloads = preGatePayloads(ctx, gateEvent, sections);
      const targets = [...payloadTargets(payloads), ...adaptedTargets(adapted, ctx.cwd)];
      if (adapted.requiresTarget && targets.length === 0) {
        if (event.toolCallId) ledger.rejectTool(session, event.toolCallId);
        return { block: true, reason: UNRESOLVED_EDIT_TARGET };
      }
      for (const payload of payloads) {
        const result = run("PreToolUse", payload);
        const reason = blockReason(result);
        if (reason) {
          if (trackedMutation && event.toolCallId) ledger.rejectTool(session, event.toolCallId);
          return { block: true, reason: sanitizeDisplay(reason, 16 * 1024) };
        }
      }
      if (trackedMutation && event.toolCallId) {
        ledger.acceptTool(session, event.toolCallId, targets, adaptedDeletedTargets(adapted, ctx.cwd));
      }
      return undefined;
    } catch (error) {
      if (trackedMutation && event.toolCallId) ledger.rejectTool(session, event.toolCallId);
      return {
        block: true,
        reason: sanitizeDisplay(error instanceof Error ? error.message : "agent-discipline-watcher PreToolUse failed", 16 * 1024),
      };
    }
  });

  pi.on("user_python", async (event: UserPythonEvent, ctx: ExtensionContext) => {
    const adapted = adaptPythonEvent(event);
    try {
      const result = run("PreToolUse", watcherPayload(ctx.cwd, sessionId(ctx), adapted.hookToolName, adapted.input));
      const reason = blockReason(result);
      if (reason) return { result: pythonFailureResult(reason) };
      return undefined;
    } catch (error) {
      return { result: pythonFailureResult(error instanceof Error ? error.message : "agent-discipline-watcher Python gate failed") };
    }
  });

  pi.on("tool_result", async (event: ToolResultEvent, ctx: ExtensionContext) => {
    let adapted: AdaptedTool;
    try {
      adapted = adaptToolResult(event);
    } catch {
      adapted = { kind: "unknown-write", hookToolName: event.toolName, input: event.input, requiresTarget: true, reason: UNKNOWN_OMP_WRITE };
    }
    const scanMutation = isPostScanTool(event.toolName) || ["write", "bash", "notebook", "python", "unknown-write"].includes(adapted.kind);
    if (!scanMutation) return undefined;
    const session = sessionId(ctx);
    const targetRequired = adapted.requiresTarget;
    const paths = new Set<string>();
    try {
      for (const path of postToolPaths(adapted.input, event.details, event.content, ctx.cwd)) paths.add(path);
    } catch {
      paths.clear();
    }
    addAdaptedTargets(paths, adapted, ctx.cwd);
    if (event.toolCallId) {
      for (const path of ledger.acceptedTargets(session, event.toolCallId)) paths.add(path);
    }
    const deletedTargets = new Set(
      event.toolCallId ? ledger.acceptedDeletedTargets(session, event.toolCallId) : [],
    );
    if (event.isError) {
      let result;
      try {
        result = run("PostToolUseFailure", eventFailurePayload(ctx, event, adapted));
      } catch {
        result = { decision: "block" as const, reason: "PostToolUseFailure watcher failed" };
      }
      const messages: string[] = [];
      const message = feedbackMessage(result);
      if (message) messages.push(message);
      if (event.toolCallId && ledger.acceptedTool(session, event.toolCallId)) {
        for (const target of ledger.acceptedTargets(session, event.toolCallId)) {
          if (mayContainWrittenContent(target)) ledger.markPending(session, target);
        }
      }
      if (event.toolCallId) ledger.finishTool(session, event.toolCallId);
      const combined = [...new Set(messages)].join("\n\n");
      return combined ? { content: appendNotice(event.content, combined) } : undefined;
    }
    if (paths.size === 0) {
      if (!targetRequired) {
        if (event.toolCallId) ledger.finishTool(session, event.toolCallId);
        return undefined;
      }
      ledger.markUnknown(session);
      if (event.toolCallId) ledger.finishTool(session, event.toolCallId);
      return { content: appendNotice(event.content, UNRESOLVED_EDIT_SCAN) };
    }
    const messages: string[] = [];
    for (const filePath of paths) {
      if (deletedTargets.has(filePath) && isMissingPath(filePath)) {
        ledger.clearTarget(session, filePath);
        continue;
      }
      try {
        const result = run("PostToolUse", watcherPayload(ctx.cwd, session, adapted.hookToolName, { file_path: filePath }, event.toolCallId));
        if (result.decision === "block" || blockReason(result)) {
          ledger.markPending(session, filePath);
          messages.push("PostToolUse watcher could not verify the completed tool result.");
          continue;
        }
        const message = feedbackMessage(result);
        if (message) messages.push(message);
        const reviewed = await review(ctx, watcherPayload(ctx.cwd, session, adapted.hookToolName, { file_path: filePath }, event.toolCallId));
        const reviewReason = blockReason(reviewed);
        if (reviewed.decision === "block" || reviewReason) {
          const reason = reviewReason || "OMP review could not verify the completed tool result.";
          ledger.markPending(session, filePath, reason);
          messages.push(reason);
          continue;
        }
        const reviewMessage = feedbackMessage(reviewed);
        if (reviewMessage) messages.push(reviewMessage);
        ledger.clearTarget(session, filePath);
      } catch {
        ledger.markPending(session, filePath);
        messages.push("PostToolUse watcher failed. Treat the result as unscanned.");
      }
    }
    if (event.toolCallId) ledger.finishTool(session, event.toolCallId);
    const message = [...new Set(messages)].join("\n\n");
    return message ? { content: appendNotice(event.content, message) } : undefined;
  });

  pi.on("session_stop", async (event: SessionStopEvent, ctx: ExtensionContext): Promise<SessionStopResult> => {
    const session = sessionId(ctx);
    const recoveryMessages: string[] = [];
    for (const target of ledger.pendingTargets(session)) {
      if (target === VerificationLedger.UNKNOWN_TARGET) continue;
      try {
        const post = run("PostToolUse", watcherPayload(ctx.cwd, session, "Write", { file_path: target }));
        if (post.decision === "block" || blockReason(post)) continue;
        const reviewed = await review(ctx, watcherPayload(ctx.cwd, session, "Write", { file_path: target }), event.signal);
        const reason = blockReason(reviewed);
        if (reviewed.decision === "block" || reason) {
          ledger.markPending(session, target, reason || "OMP review could not verify this file.");
          continue;
        }
        const feedback = feedbackMessage(reviewed) ?? feedbackMessage(post);
        if (feedback) recoveryMessages.push(feedback);
        ledger.clearTarget(session, target);
      } catch {
        continue;
      }
    }
    if (ledger.hasPending(session)) {
      return {
        decision: "block",
        reason: sanitizeDisplay(ledger.pendingReasons(session).join("\n\n") || "agent-discipline-watcher could not verify every mutating tool result. Re-verify the touched file before stopping.", 16 * 1024),
      };
    }
    try {
      const payload = watcherPayload(ctx.cwd, session);
      if (stopHookRetryActive(event)) payload.stop_hook_active = true;
      const result = run("Stop", payload);
      if (result.decision === "block") {
        return { decision: "block", reason: sanitizeDisplay(result.reason || "Fix the blocked findings before stopping", 16 * 1024) };
      }
      const additionalContext = feedbackMessage(result);
      const context = [...new Set([...recoveryMessages, additionalContext].filter((message): message is string => Boolean(message)))].join("\n\n");
      return context ? { continue: true, additionalContext: sanitizeDisplay(context, 16 * 1024) } : undefined;
    } catch (error) {
      return { decision: "block", reason: sanitizeDisplay(error instanceof Error ? error.message : "Stop watcher failed", 16 * 1024) };
    }
  });
}
