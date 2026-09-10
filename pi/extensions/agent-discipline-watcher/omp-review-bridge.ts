import { execFileSync } from "node:child_process";
import { resolveRunner, type WatcherResult } from "./watcher";

export type ReviewRequest = { id: number; prompt: string; schema: Record<string, unknown> };
export type PreparedReview = {
  enabled: boolean;
  model?: string;
  path?: string;
  digest?: string;
  requests: ReviewRequest[];
};
export type ReviewBridge = (request: Record<string, unknown>) => unknown;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function prepareReview(value: unknown): PreparedReview {
  if (!record(value) || typeof value.enabled !== "boolean" || !Array.isArray(value.requests)) {
    throw new Error("OMP review bridge returned an invalid preparation");
  }
  if (value.requests.length > 16 || (!value.enabled && value.requests.length)) {
    throw new Error("OMP review bridge returned an invalid request count");
  }
  const requests = value.requests.map((request, index) => {
    if (!record(request) || request.id !== index || typeof request.prompt !== "string" || !request.prompt.trim() || !record(request.schema)) {
      throw new Error("OMP review bridge returned an invalid model request");
    }
    return { id: index, prompt: request.prompt, schema: request.schema };
  });
  if (requests.length && [value.model, value.path, value.digest].some(item => typeof item !== "string")) {
    throw new Error("OMP review bridge omitted the model or source identity");
  }
  return { ...value, requests } as PreparedReview;
}

export function validatedReview(value: unknown): WatcherResult {
  if (!record(value) || Object.keys(value).some(key => !["decision", "reason", "systemMessage"].includes(key))) {
    throw new Error("OMP review bridge returned an invalid verdict");
  }
  if ((value.decision !== undefined && value.decision !== "block") ||
      (value.reason !== undefined && typeof value.reason !== "string") ||
      (value.systemMessage !== undefined && typeof value.systemMessage !== "string") ||
      (value.decision === "block" && !value.reason)) {
    throw new Error("OMP review bridge returned an incomplete verdict");
  }
  return value as WatcherResult;
}

export function runReviewBridge(request: Record<string, unknown>, runner = resolveRunner()): unknown {
  const input = JSON.stringify(request);
  if (Buffer.byteLength(input, "utf8") > 256 * 1024) throw new Error("OMP review bridge input exceeds 256 KiB");
  let output: string;
  try {
    output = execFileSync(runner, ["OmpReview"], {
      input, encoding: "utf8", env: { ...process.env, OMPCODE: "1" },
      timeout: 30_000, maxBuffer: 1024 * 1024,
    });
  } catch {
    throw new Error("OMP review bridge could not run. Check the ADW Python runtime and reinstall ADW if needed.");
  }
  const response: unknown = JSON.parse(output);
  if (!record(response) || response.ok !== true) {
    throw new Error(record(response) && typeof response.error === "string" ? response.error : "OMP review bridge returned an invalid response");
  }
  return response.result;
}
