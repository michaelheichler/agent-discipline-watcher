import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

import {
  blockReason,
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

function appendNotice(
  content: Array<{ type: string; text?: string }>,
  message: string,
): Array<{ type: string; text?: string }> {
  const notice = `\n\n[agent-discipline-watcher]\n${message}`;
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

function createExtension(pi: ExtensionAPI, run: WatcherRun = runWatcher) {
  pi.on("session_start", async (_event, ctx: ExtensionContext) => {
    const result = run(
      "SessionStart",
      watcherPayload(ctx.cwd, sessionId(ctx)),
    );
    const message = feedbackMessage(result);
    if (message) {
      await pi.sendMessage(
        {
          customType: "agent-discipline-watcher.context",
          content: message,
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
    const lower = event.toolName.toLowerCase();
    if (lower === "write") {
      const target = String(event.input.path ?? event.input.file_path ?? "").trim();
      if (target && !isPlainFilePath(target)) {
        return undefined;
      }
    }
    try {
      const result = run(
        "PreToolUse",
        watcherPayload(
          ctx.cwd,
          sessionId(ctx),
          event.toolName,
          event.input,
          event.toolCallId,
        ),
      );
      const reason = blockReason(result);
      if (reason) {
        return { block: true, reason };
      }
      return undefined;
    } catch (error) {
      return {
        block: true,
        reason: error instanceof Error ? error.message : "agent-discipline-watcher PreToolUse failed",
      };
    }
  });

  pi.on("tool_result", async (event: ToolResultEvent, ctx: ExtensionContext) => {
    if (event.isError || !isPostScanTool(event.toolName)) {
      return undefined;
    }
    const paths = postToolPaths(event.input, event.details, event.content);
    if (paths.length === 0 && event.toolName.toLowerCase() === "edit") {
      return { content: appendNotice(event.content, UNRESOLVED_EDIT_SCAN) };
    }
    const messages: string[] = [];
    const targets = paths.length > 0 ? paths : [""];
    for (const filePath of targets) {
      // Avoid exposing raw write content because landed files are rescanned from disk, while the Bash fallback still needs its command for write detection.
      const toolInput = filePath ? { file_path: filePath } : event.input;
      const result = run(
        "PostToolUse",
        watcherPayload(
          ctx.cwd,
          sessionId(ctx),
          event.toolName,
          toolInput,
          event.toolCallId,
        ),
      );
      const message = feedbackMessage(result);
      if (message) {
        messages.push(message);
      }
    }
    const message = [...new Set(messages)].join("\n\n");
    if (!message) {
      return undefined;
    }
    return { content: appendNotice(event.content, message) };
  });

  pi.on("session_stop", async (event: SessionStopEvent, ctx: ExtensionContext): Promise<SessionStopResult> => {
    const payload = watcherPayload(ctx.cwd, sessionId(ctx));
    if (stopHookRetryActive(event)) {
      payload.stop_hook_active = true;
    }
    const result = run("Stop", payload);
    if (result.decision === "block") {
      return {
        decision: "block",
        reason: result.reason || "Fix the blocked findings before stopping",
      };
    }
    const additionalContext = feedbackMessage(result);
    if (additionalContext) {
      return { continue: true, additionalContext };
    }
    return undefined;
  });
}

export default function (pi: ExtensionAPI) {
  createExtension(pi);
}

export { createExtension };
