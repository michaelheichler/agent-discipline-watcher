import { execFileSync } from "node:child_process";
import { isAbsolute } from "node:path";
import { isRecord } from "./adw-config";
import { resolveRunner, type WatcherResult } from "./watcher";

export type ReviewRequest = { id: number; prompt: string; schema: Record<string, unknown>; instructions: string };
export type PreparedReview = {
  enabled: boolean;
  model?: string;
  path?: string;
  digest?: string;
  requests: ReviewRequest[];
};
export type ReviewBridge = (request: Record<string, unknown>) => unknown;

const MAX_REVIEW_REQUESTS = 16;
const MAX_REVIEW_PROMPT_CHARS = 256 * 1024;
const MAX_REVIEW_INSTRUCTION_CHARS = 16 * 1024;
const MAX_REVIEW_FEEDBACK_CHARS = 64 * 1024;
const MAX_SCHEMA_DEPTH = 8;
const MAX_SCHEMA_FIELDS = 64;
const MAX_MODEL_ID_CHARS = 256;
const MAX_SOURCE_PATH_CHARS = 4096;

export function validatedTargetPaths(value: unknown): string[] {
  if (!isRecord(value) || !Array.isArray(value.paths) || value.paths.length > 32) {
    throw new Error("OMP target bridge returned invalid paths");
  }
  const paths = value.paths.map(path => {
    if (typeof path !== "string" || !path.trim() || path.length > 4096 || /["'\\]/u.test(path)) {
      throw new Error("OMP target bridge returned invalid paths");
    }
    return path;
  });
  return [...new Set(paths)];
}

function boundedText(value: unknown, limit: number): value is string {
  return typeof value === "string" && !!value.trim() && value.length <= limit && !value.includes("\0");
}

function validatedSchema(value: unknown, depth = 0): Record<string, unknown> {
  if (!isRecord(value) || depth > MAX_SCHEMA_DEPTH) throw new Error("OMP review bridge returned an invalid schema");
  const allowed = ["type", "additionalProperties", "required", "properties", "items", "enum", "maxItems"];
  if (Object.keys(value).some(key => !allowed.includes(key))) throw new Error("OMP review bridge returned an unsupported schema");
  if (Object.hasOwn(value, "maxItems") && (value.type !== "array" ||
      typeof value.maxItems !== "number" || !Number.isSafeInteger(value.maxItems) || value.maxItems < 0)) {
    throw new Error("OMP review bridge returned an invalid array item limit");
  }
  if (value.type === "object") {
    const properties = value.properties;
    if (value.additionalProperties !== false || !isRecord(properties) || !Object.keys(properties).length ||
        Object.keys(properties).length > MAX_SCHEMA_FIELDS || !Array.isArray(value.required) ||
        value.required.length !== Object.keys(properties).length || new Set(value.required).size !== value.required.length ||
        value.required.some(key => typeof key !== "string" || !Object.hasOwn(properties, key))) {
      throw new Error("OMP review bridge returned an invalid object schema");
    }
    for (const child of Object.values(properties)) validatedSchema(child, depth + 1);
  } else if (value.type === "array") {
    validatedSchema(value.items, depth + 1);
  } else if (value.type !== "string" && value.type !== "integer") {
    throw new Error("OMP review bridge returned an unsupported schema type");
  }
  if (value.enum !== undefined && (!Array.isArray(value.enum) || !value.enum.length || value.enum.length > MAX_SCHEMA_FIELDS ||
      value.enum.some(item => value.type === "string" ? typeof item !== "string" : !Number.isInteger(item)))) {
    throw new Error("OMP review bridge returned an invalid schema enum");
  }
  return value;
}

function reviewRequest(value: unknown, index: number): ReviewRequest {
  if (!isRecord(value) || value.id !== index || !boundedText(value.prompt, MAX_REVIEW_PROMPT_CHARS) ||
      !boundedText(value.instructions, MAX_REVIEW_INSTRUCTION_CHARS)) {
    throw new Error("OMP review bridge returned an invalid model request");
  }
  const schema = validatedSchema(value.schema);
  if (schema.type !== "object") throw new Error("OMP review bridge returned an invalid response schema");
  return { id: index, prompt: value.prompt, schema, instructions: value.instructions };
}

export function prepareReview(value: unknown): PreparedReview {
  if (!isRecord(value) || typeof value.enabled !== "boolean" || !Array.isArray(value.requests) ||
      Object.keys(value).some(key => !["enabled", "model", "path", "digest", "requests"].includes(key))) {
    throw new Error("OMP review bridge returned an invalid preparation");
  }
  if (value.requests.length > MAX_REVIEW_REQUESTS || (!value.enabled && value.requests.length)) {
    throw new Error("OMP review bridge returned an invalid request count");
  }
  const result: PreparedReview = { enabled: value.enabled, requests: value.requests.map(reviewRequest) };
  if (value.model !== undefined) {
    if (typeof value.model !== "string" || value.model.length > MAX_MODEL_ID_CHARS || /\s|[\x00-\x1f]/u.test(value.model)) {
      throw new Error("OMP review bridge returned an invalid model identity");
    }
    result.model = value.model;
  }
  if (value.path !== undefined) {
    if (!boundedText(value.path, MAX_SOURCE_PATH_CHARS) || !isAbsolute(value.path)) throw new Error("OMP review bridge returned an invalid source path");
    result.path = value.path;
  }
  if (value.digest !== undefined) {
    if (typeof value.digest !== "string" || !/^[a-f0-9]{64}$/u.test(value.digest)) throw new Error("OMP review bridge returned an invalid source digest");
    result.digest = value.digest;
  }
  if (result.requests.length && (result.model === undefined || !result.path || !result.digest)) {
    throw new Error("OMP review bridge omitted the model or source identity");
  }
  return result;
}

export function validatedReview(value: unknown): WatcherResult {
  if (!isRecord(value) || Object.keys(value).some(key => !["decision", "reason", "systemMessage"].includes(key))) {
    throw new Error("OMP review bridge returned an invalid verdict");
  }
  if ((value.decision !== undefined && value.decision !== "block") ||
      (value.reason !== undefined && !boundedText(value.reason, MAX_REVIEW_FEEDBACK_CHARS)) ||
      (value.systemMessage !== undefined && !boundedText(value.systemMessage, MAX_REVIEW_FEEDBACK_CHARS)) ||
      (value.decision === "block" && value.reason === undefined) ||
      (value.reason !== undefined && value.decision !== "block")) {
    throw new Error("OMP review bridge returned an incomplete verdict");
  }
  const result: WatcherResult = {};
  if (value.decision === "block" && typeof value.reason === "string") {
    result.decision = "block";
    result.reason = value.reason;
  }
  if (typeof value.systemMessage === "string") result.systemMessage = value.systemMessage;
  return result;
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
  if (!isRecord(response) || response.ok !== true) {
    throw new Error(isRecord(response) && typeof response.error === "string" ? response.error : "OMP review bridge returned an invalid response");
  }
  return response.result;
}
