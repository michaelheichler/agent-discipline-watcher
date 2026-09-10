import { describe, expect, test } from "bun:test";
import type { Api, AssistantMessage, Context, Model, SimpleStreamOptions } from "@oh-my-pi/pi-ai";
import { completeOmpJudge, OmpProviderFailure } from "./omp-provider";

const FIRST_MODEL = { provider: "ollama", id: "llama3", api: "openai-completions" } as unknown as Model<Api>;
const SECOND_MODEL = { provider: "anthropic", id: "claude-haiku", api: "anthropic-messages" } as unknown as Model<Api>;

function context(
  current: Model<Api> | undefined = FIRST_MODEL,
  models: Model<Api>[] = [FIRST_MODEL],
  calls: { key: number; resolver: number; complete: number } = { key: 0, resolver: 0, complete: 0 },
) {
  return {
    model: current,
    models: {
      list: () => models,
      current: () => current,
      resolve: (id: string) => models.find(model => `${model.provider}/${model.id}` === id || model.id === id),
    },
    modelRegistry: {
      getApiKey: async () => {
        calls.key += 1;
        return "local-key";
      },
      resolver: () => {
        calls.resolver += 1;
        return "local-key";
      },
    },
    sessionManager: { getSessionId: () => "session-1" },
    calls,
  } as never;
}

function answer(text: string): AssistantMessage {
  return { content: [{ type: "text", text }] } as AssistantMessage;
}

describe("completeOmpJudge", () => {
  test("does not resolve a model when the data boundary is off", async () => {
    const calls = { key: 0, resolver: 0, complete: 0 };
    const ctx = context(FIRST_MODEL, [FIRST_MODEL], calls);
    const complete = async () => {
      calls.complete += 1;
      return answer("should not run");
    };

    await expect(completeOmpJudge(ctx, { prompt: "review", dataBoundary: { enabled: false } }, complete)).resolves.toBeUndefined();
    expect(calls).toEqual({ key: 0, resolver: 0, complete: 0 });
  });

  test("uses the requested authenticated model and session resolver", async () => {
    const calls = { key: 0, resolver: 0, complete: 0 };
    const ctx = context(FIRST_MODEL, [FIRST_MODEL, SECOND_MODEL], calls);
    let receivedModel: Model<Api> | undefined;
    let receivedContext: Context | undefined;
    let receivedOptions: SimpleStreamOptions | undefined;
    const complete = async (model: Model<Api>, request: Context, options?: SimpleStreamOptions) => {
      calls.complete += 1;
      receivedModel = model;
      receivedContext = request;
      receivedOptions = options;
      return answer("{\"notes\":[]}");
    };

    const result = await completeOmpJudge(
      ctx,
      { prompt: "review this", systemPrompt: "return JSON", modelId: "anthropic/claude-haiku", dataBoundary: { enabled: true } },
      complete,
    );

    expect(result).toEqual({ text: "{\"notes\":[]}", model: "claude-haiku", provider: "anthropic" });
    expect(receivedModel).toBe(SECOND_MODEL);
    expect(receivedContext?.systemPrompt).toEqual(["return JSON"]);
    expect(receivedContext?.messages[0]).toMatchObject({ role: "user", content: "review this" });
    expect(receivedOptions).toMatchObject({ sessionId: "session-1", disableReasoning: true });
    expect(calls).toEqual({ key: 1, resolver: 1, complete: 1 });
  });

  test("rejects a requested model outside the authenticated catalogue", async () => {
    const ctx = context(FIRST_MODEL, [FIRST_MODEL]);

    await expect(completeOmpJudge(
      ctx,
      { prompt: "review", modelId: "anthropic/claude-haiku", dataBoundary: { enabled: true } },
      async () => answer("unused"),
    )).rejects.toMatchObject({ category: "model" });
  });

  test("names provider failures instead of returning a clean review", async () => {
    const ctx = context();

    await expect(completeOmpJudge(
      ctx,
      { prompt: "review", dataBoundary: { enabled: true } },
      async () => {
        throw new Error("model unavailable");
      },
    )).rejects.toBeInstanceOf(OmpProviderFailure);
  });

  test("rejects error completions even when they contain valid review JSON", async () => {
    await expect(completeOmpJudge(
      context(),
      { prompt: "review", dataBoundary: { enabled: true } },
      async () => ({ ...answer('{"notes":[]}'), stopReason: "error", errorMessage: "provider overloaded" }),
    )).rejects.toMatchObject({ category: "provider" });
  });

  test("bounds a stalled completion and aborts its provider request", async () => {
    let signal: AbortSignal | undefined;
    await expect(completeOmpJudge(
      context(),
      { prompt: "review", dataBoundary: { enabled: true }, timeoutMs: 10 },
      async (_model, _request, options) => {
        signal = options?.signal;
        return new Promise(() => {});
      },
    )).rejects.toMatchObject({ category: "timeout" });
    expect(signal?.aborted).toBe(true);
  });

  test("bounds authentication lookup before it reaches a provider", async () => {
    const ctx = context() as unknown as { modelRegistry: { getApiKey: () => Promise<undefined> } };
    ctx.modelRegistry.getApiKey = () => new Promise(() => {});
    await expect(completeOmpJudge(
      ctx as never,
      { prompt: "review", dataBoundary: { enabled: true }, timeoutMs: 10 },
      async () => answer("unused"),
    )).rejects.toMatchObject({ category: "timeout" });
  });
});
