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
import { preGatePayloads, registerLifecycleHandlers } from "./lifecycle-handlers";
import { createOmpReviewer, type OmpReviewRun } from "./omp-review";
import { runWatcher, type WatcherRun } from "./watcher";

const JUDGES_INACTIVE =
  "Data boundary is off, so every model judge stays inactive and only the regex rules run.";

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
    .map(model => `${model.provider}/${model.id}`)
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

  if (!judgesAreActive(state)) ctx.ui.notify(JUDGES_INACTIVE, "warning");

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
  review: OmpReviewRun = createOmpReviewer(),
) {
  registerAdwCommands(pi, bridge);
  registerLifecycleHandlers(pi, run, review);
}

export default function (pi: ExtensionAPI) {
  createExtension(pi);
}

export { createExtension, preGatePayloads };
