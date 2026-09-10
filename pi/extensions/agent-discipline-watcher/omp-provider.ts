import { completeSimple, type Api, type AssistantMessage, type Context, type Model, type SimpleStreamOptions } from "@oh-my-pi/pi-ai";
import type { ExtensionContext } from "@oh-my-pi/pi-coding-agent";

export type OmpContext = Pick<ExtensionContext, "model" | "models" | "modelRegistry" | "sessionManager">;

export type OmpJudgeRequest = {
  prompt: string;
  systemPrompt?: string;
  modelId?: string;
  dataBoundary: unknown;
  signal?: AbortSignal;
  maxTokens?: number;
  timeoutMs?: number;
};

export type OmpJudgeResult = {
  text: string;
  model: string;
  provider: string;
};

export class OmpProviderFailure extends Error {
  readonly category: string;

  constructor(message: string, category = "provider") {
    super(message);
    this.name = "OmpProviderFailure";
    this.category = category;
  }
}

export type CompleteSimple = typeof completeSimple;

function boundaryEnabled(value: unknown): boolean {
  return typeof value === "object" && value !== null && !Array.isArray(value) && (value as { enabled?: unknown }).enabled === true;
}

function modelKey(model: Model<Api>): string {
  return `${model.provider}/${model.id}`;
}

function availableModel(models: readonly Model<Api>[], model: Model<Api>): Model<Api> | undefined {
  return models.find(candidate => candidate.provider === model.provider && candidate.id === model.id);
}

function selectedModel(ctx: OmpContext, requested: string | undefined): Model<Api> {
  const available = ctx.models.list();
  const model = requested?.trim() ? ctx.models.resolve(requested) : ctx.model ?? ctx.models.current();
  if (!model) throw new OmpProviderFailure("OMP has no selected model for ADW review", "model");
  if (!availableModel(available, model)) {
    throw new OmpProviderFailure(`OMP model is not an allowed authenticated choice: ${modelKey(model)}`, "model");
  }
  return model;
}

function responseText(message: AssistantMessage): string {
  if (message.stopReason === "error" || message.stopReason === "aborted") {
    throw new OmpProviderFailure(message.errorMessage || `OMP review ended with ${message.stopReason}`);
  }
  if (message.stopReason === "length") throw new OmpProviderFailure("OMP review exceeded its output token limit", "response");
  return message.content.reduce((text, block) => block.type === "text" ? `${text}${block.text}` : text, "");
}

function requestContext(request: OmpJudgeRequest): Context {
  return {
    systemPrompt: request.systemPrompt ? [request.systemPrompt] : [],
    messages: [{ role: "user", content: request.prompt, timestamp: Date.now() }],
  };
}

function streamOptions(
  ctx: OmpContext,
  model: Model<Api>,
  request: OmpJudgeRequest,
  sessionId: string,
): SimpleStreamOptions {
  return {
    apiKey: ctx.modelRegistry.resolver(model, sessionId),
    sessionId,
    maxTokens: request.maxTokens ?? 4096,
    disableReasoning: true,
    signal: request.signal,
  };
}

export async function completeOmpJudge(
  ctx: OmpContext,
  request: OmpJudgeRequest,
  complete: CompleteSimple = completeSimple,
): Promise<OmpJudgeResult | undefined> {
  if (!boundaryEnabled(request.dataBoundary)) return undefined;
  if (!request.prompt.trim()) throw new OmpProviderFailure("OMP review prompt is empty", "request");
  try {
    return await timedCompletion(ctx, request, complete);
  } catch (error) {
    if (error instanceof OmpProviderFailure) throw error;
    throw new OmpProviderFailure(error instanceof Error ? error.message : String(error));
  }
}

async function invokeCompletion(ctx: OmpContext, request: OmpJudgeRequest, complete: CompleteSimple): Promise<OmpJudgeResult> {
  const model = selectedModel(ctx, request.modelId);
  const sessionId = ctx.sessionManager.getSessionId();
  const apiKey = await ctx.modelRegistry.getApiKey(model, sessionId, { signal: request.signal });
  if (apiKey === undefined) throw new OmpProviderFailure(`OMP has no credentials for ${modelKey(model)}`, "authentication");
  request.signal?.throwIfAborted();
  const message = await complete(model, requestContext(request), streamOptions(ctx, model, request, sessionId));
  const text = responseText(message).trim();
  if (!text) throw new OmpProviderFailure("OMP model returned an empty review", "response");
  if (Buffer.byteLength(text, "utf8") > 64 * 1024) throw new OmpProviderFailure("OMP model review exceeds 64 KiB", "response");
  return { text, model: model.id, provider: model.provider };
}

async function timedCompletion(ctx: OmpContext, request: OmpJudgeRequest, complete: CompleteSimple): Promise<OmpJudgeResult> {
  const duration = request.timeoutMs ?? 30_000;
  if (!Number.isFinite(duration) || duration <= 0) throw new OmpProviderFailure("OMP review timeout must be positive", "request");
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancel = () => {};
  const deadline = new Promise<never>((_resolve, reject) => {
    cancel = () => {
      controller.abort();
      reject(new OmpProviderFailure("OMP review was cancelled", "cancelled"));
    };
    request.signal?.addEventListener("abort", cancel, { once: true });
    timer = setTimeout(() => {
      controller.abort();
      reject(new OmpProviderFailure(`OMP review timed out after ${duration} ms`, "timeout"));
    }, Math.min(duration, 120_000));
  });
  try {
    if (request.signal?.aborted) cancel();
    return await Promise.race([deadline, invokeCompletion(ctx, { ...request, signal: controller.signal }, complete)]);
  } finally {
    clearTimeout(timer);
    request.signal?.removeEventListener("abort", cancel);
  }
}
