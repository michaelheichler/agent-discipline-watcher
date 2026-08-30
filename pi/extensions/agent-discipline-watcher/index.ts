import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import type { Component, TUI } from "@oh-my-pi/pi-tui";
import {
  AdwBridgeError,
  AdwConfigOverlayComponent,
  bridgeResponseError,
  decodeAdwPolicy,
  isRecord,
  runConfigureBridge,
  sanitizeDisplay,
  type AdwBridgeRunner,
  type AdwConfigOutcome,
  type AdwPolicyState,
} from "./adw-config";
import {
  hashlineEdits,
  hashlinePatchSource,
  type HashlineEdit,
} from "./hashline";
import {
  blockReason,
  canonicalPath,
  feedbackMessage,
  isPlainFilePath,
  isPostScanTool,
  isPreGateTool,
  postToolPaths,
  runWatcher,
  watcherPayload,
  type WatcherRun,
} from "./watcher";

type ExtensionContext = {
  cwd: string;
  sessionManager: {
    getSessionId(): string;
  };
};

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
};

type SessionStopResult =
  | { decision: "block"; reason: string }
  | { continue: true; additionalContext?: string }
  | undefined;

function sessionId(ctx: ExtensionContext): string {
  return ctx.sessionManager.getSessionId();
}

function stopHookRetryActive(event: SessionStopEvent): boolean {
  return Boolean(event.stop_hook_active ?? event.stopHookActive);
}

const UNRESOLVED_EDIT_SCAN =
  "agent-discipline-watcher could not resolve the edited file path from this edit result. Re-verify the touched file before finishing.";

const JUDGES_INACTIVE =
  "Data boundary is off, so every model judge stays inactive and only the regex rules run.";

const UNDECODABLE_EDIT =
  "agent-discipline-watcher could not decode this edit patch, so nothing was scanned. Split it into fewer sections and retry.";

const UNRESOLVED_EDIT_TARGET =
  "agent-discipline-watcher could not resolve an edit target inside the session directory, so nothing was scanned.";

function appendNotice(
  content: Array<{ type: string; text?: string }>,
  message: string,
): Array<{ type: string; text?: string }> {
  const notice = `\n\n[agent-discipline-watcher]\n${sanitizeDisplay(message, 16 * 1024)}`;
  const updated = content.map((chunk) => {
    if (chunk.type !== "text") {
      return chunk;
    }
    return { ...chunk, text: `${chunk.text ?? ""}${notice}` };
  });
  if (!updated.some((chunk) => chunk.type === "text")) {
    updated.push({ type: "text", text: notice.trimStart() });
  }
  return updated;
}

function toolFailureText(content: Array<{ type: string; text?: string }>): string {
  const text = content
    .filter((chunk) => chunk.type === "text" && typeof chunk.text === "string")
    .map((chunk) => chunk.text ?? "")
    .join("\n");
  return sanitizeDisplay(text, 1024) || "tool result reported an error";
}

function eventFailurePayload(
  ctx: ExtensionContext,
  event: ToolResultEvent,
): Record<string, unknown> {
  const payload = watcherPayload(
    ctx.cwd,
    sessionId(ctx),
    event.toolName,
    event.input,
    event.toolCallId,
  );
  payload.error = toolFailureText(event.content);
  payload.is_interrupt = false;
  payload.duration_ms = 0;
  return payload;
}

export function preGatePayloads(
  ctx: ExtensionContext,
  event: ToolCallEvent,
  sections: readonly HashlineEdit[],
): Array<Record<string, unknown>> {
  if (sections.length === 0) {
    return [
      watcherPayload(ctx.cwd, sessionId(ctx), event.toolName, event.input, event.toolCallId),
    ];
  }
  return sections.map((section) => {
    const target = canonicalPath(section.path, ctx.cwd);
    if (target === undefined) {
      throw new Error(UNRESOLVED_EDIT_TARGET);
    }
    return watcherPayload(
      ctx.cwd,
      sessionId(ctx),
      event.toolName,
      { file_path: target, new_string: section.added },
      event.toolCallId,
    );
  });
}

type AdwCommandContext = {
  cwd: string;
  hasUI: boolean;
  models?: {
    list(): Array<{ provider: string; id: string }>;
  };
  ui: {
    notify(message: string, type?: "info" | "warning" | "error"): void;
    custom<T>(
      factory: (
        tui: TUI,
        theme: unknown,
        keybindings: unknown,
        done: (result: AdwConfigOutcome) => void,
      ) => Component | Promise<Component>,
      options?: {
        overlay?: boolean;
        overlayOptions?: { fullscreen?: boolean; mouseTracking?: boolean };
      },
    ): Promise<T>;
  };
};

type CommandRegistrar = (
  name: string,
  spec: { description: string; handler: (args: string, ctx: AdwCommandContext) => Promise<void> },
) => void;

function bridgeErrorText(error: unknown): string {
  if (error instanceof AdwBridgeError) {
    return sanitizeDisplay(error.message, 240) || "ADW configuration bridge failed";
  }
  return "ADW configuration bridge failed";
}

function judgesAreActive(state: AdwPolicyState): boolean {
  const boundary = state.effective.data_boundary;
  return isRecord(boundary) && boundary.enabled === true;
}

export function selectableModels(models: Array<{ provider: string; id: string }>): string[] {
  return models
    .map(model => model.id)
    .filter(model => sanitizeDisplay(model, 256) === model)
    .slice(0, 256);
}

async function openAdwConfigure(
  args: string,
  ctx: AdwCommandContext,
  bridge: AdwBridgeRunner,
): Promise<void> {
  if (args.trim().toLowerCase() !== "configure") {
    ctx.ui.notify("Usage: /adw configure", "info");
    return;
  }
  if (!ctx.hasUI) {
    ctx.ui.notify("/adw configure is only available in the interactive TUI", "info");
    return;
  }

  let state: AdwPolicyState;
  try {
    const response = bridge({ operation: "read", cwd: ctx.cwd });
    const error = bridgeResponseError(response);
    if (error) throw error;
    state = decodeAdwPolicy(response);
  } catch (error) {
    ctx.ui.notify(bridgeErrorText(error), "error");
    return;
  }

  if (!judgesAreActive(state)) {
    ctx.ui.notify(JUDGES_INACTIVE, "warning");
  }

  const outcome = await ctx.ui.custom(
    (tui, _theme, _keybindings, done) =>
      new AdwConfigOverlayComponent(tui, state, {
        availableModels: selectableModels(ctx.models?.list() ?? []),
        close: done,
        requestRender: () => tui.requestRender(),
        notify: (message, type) => ctx.ui.notify(sanitizeDisplay(message, 240), type),
        save: async (expectedDigest, values) => {
          const response = bridge({
            operation: "write",
            cwd: ctx.cwd,
            expected_digest: expectedDigest,
            values,
          });
          const error = bridgeResponseError(response);
          if (error) throw error;
          return decodeAdwPolicy(response);
        },
      }),
    { overlay: true, overlayOptions: { fullscreen: true, mouseTracking: true } },
  );
  if (outcome === "saved") ctx.ui.notify("ADW policy saved for the next watcher call", "info");
}

function registerAdwCommands(pi: ExtensionAPI, bridge: AdwBridgeRunner): void {
  const registerCommand = (pi as unknown as { registerCommand?: CommandRegistrar }).registerCommand;
  if (typeof registerCommand !== "function") return;
  const register = (name: string) =>
    registerCommand.call(pi, name, {
      description: "Open the ADW project policy editor",
      handler: async (args, ctx) => openAdwConfigure(args, ctx, bridge),
    });
  register("adw");
  register("agent-discipline");
}

function createExtension(
  pi: ExtensionAPI,
  run: WatcherRun = runWatcher,
  bridge: AdwBridgeRunner = runConfigureBridge,
) {
  registerAdwCommands(pi, bridge);
  const unresolvedSessions = new Set<string>();
  pi.on("session_start", async (_event, ctx: ExtensionContext) => {
    unresolvedSessions.delete(sessionId(ctx));
    try {
      const result = run(
        "SessionStart",
        watcherPayload(ctx.cwd, sessionId(ctx)),
      );
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
    if (!isPreGateTool(event.toolName)) {
      return undefined;
    }
    try {
      const sections = hashlineEdits(hashlinePatchSource(event.input));
      if (sections === undefined) {
        return { block: true, reason: UNDECODABLE_EDIT };
      }
      for (const payload of preGatePayloads(ctx, event, sections)) {
        const result = run("PreToolUse", payload);
        const reason = blockReason(result);
        if (reason) {
          return { block: true, reason: sanitizeDisplay(reason, 16 * 1024) };
        }
      }
      return undefined;
    } catch (error) {
      return {
        block: true,
        reason: sanitizeDisplay(error instanceof Error ? error.message : "agent-discipline-watcher PreToolUse failed", 16 * 1024),
      };
    }
  });
  pi.on("tool_result", async (event: ToolResultEvent, ctx: ExtensionContext) => {
    if (!isPostScanTool(event.toolName)) {
      return undefined;
    }
    const session = sessionId(ctx);
    // Bash needs no target because pre_bash gates it pre-call.
    const targetRequired = event.toolName.toLowerCase() !== "bash";
    let paths: string[];
    try {
      paths = postToolPaths(event.input, event.details, event.content, ctx.cwd);
    } catch {
      paths = [];
    }
    if (event.isError) {
      const unresolved = targetRequired && paths.length === 0;
      if (unresolved) unresolvedSessions.add(session);
      let result;
      try {
        result = run("PostToolUseFailure", eventFailurePayload(ctx, event));
      } catch {
        result = { decision: "block" as const, reason: "PostToolUseFailure watcher failed" };
      }
      const messages: string[] = [];
      const message = feedbackMessage(result);
      if (message) messages.push(message);
      if (unresolved) messages.push(UNRESOLVED_EDIT_SCAN);
      const combined = [...new Set(messages)].join("\n\n");
      return combined ? { content: appendNotice(event.content, combined) } : undefined;
    }
    if (paths.length === 0) {
      if (!targetRequired) {
        return undefined;
      }
      unresolvedSessions.add(session);
      return { content: appendNotice(event.content, UNRESOLVED_EDIT_SCAN) };
    }
    const messages: string[] = [];
    let scanFailed = false;
    for (const filePath of paths) {
      try {
        const result = run(
          "PostToolUse",
          watcherPayload(ctx.cwd, session, event.toolName, { file_path: filePath }, event.toolCallId),
        );
        if (result.decision === "block" || blockReason(result)) {
          scanFailed = true;
          messages.push("PostToolUse watcher could not verify the completed tool result.");
          continue;
        }
        const message = feedbackMessage(result);
        if (message) messages.push(message);
        const review = run(
          "JudgeReview",
          watcherPayload(ctx.cwd, session, event.toolName, { file_path: filePath }, event.toolCallId),
        );
        if (review.decision === "block" || blockReason(review)) {
          scanFailed = true;
          messages.push("JudgeReview watcher could not verify the completed tool result.");
          continue;
        }
        const reviewMessage = feedbackMessage(review);
        if (reviewMessage) messages.push(reviewMessage);
      } catch {
        scanFailed = true;
        messages.push("PostToolUse watcher failed. Treat the result as unscanned.");
      }
    }
    if (scanFailed) {
      unresolvedSessions.add(session);
    }
    const message = [...new Set(messages)].join("\n\n");
    if (!message) return undefined;
    return { content: appendNotice(event.content, message) };
  });

  pi.on("session_stop", async (event: SessionStopEvent, ctx: ExtensionContext): Promise<SessionStopResult> => {
    const session = sessionId(ctx);
    if (unresolvedSessions.has(session)) {
      return {
        decision: "block",
        reason: "agent-discipline-watcher could not verify every mutating tool result. Re-verify the touched file before stopping.",
      };
    }
    try {
      const payload = watcherPayload(ctx.cwd, session);
      if (stopHookRetryActive(event)) {
        payload.stop_hook_active = true;
      }
      const result = run("Stop", payload);
      if (result.decision === "block") {
        return {
          decision: "block",
          reason: sanitizeDisplay(result.reason || "Fix the blocked findings before stopping", 16 * 1024),
        };
      }
      const additionalContext = feedbackMessage(result);
      if (additionalContext) {
        return { continue: true, additionalContext: sanitizeDisplay(additionalContext, 16 * 1024) };
      }
      return undefined;
    } catch (error) {
      return {
        decision: "block",
        reason: sanitizeDisplay(error instanceof Error ? error.message : "Stop watcher failed", 16 * 1024),
      };
    }
  });
}

export default function (pi: ExtensionAPI) {
  createExtension(pi);
}

export { createExtension };
