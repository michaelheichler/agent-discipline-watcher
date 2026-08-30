/**
 * Owns the ADW configuration bridge contract, response decoding, and runner lifecycle.
 *
 * The TUI and display sanitizers remain in `adw-config.ts`.
 */
import { randomBytes } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";

import * as adwConfig from "./adw-config";
import { resolveRunner } from "./watcher";

const BRIDGE_MAX_OUTPUT_BYTES = 256 * 1024;
const BRIDGE_TIMEOUT_MS = 30_000;
const CAPABILITY_MAX_BYTES = 4096;
const CONFIG_VALUE_KEYS = [
  "punctuation",
  "english",
  "clean_code",
  "max_rows",
  "sentence_word_cap",
  "list_item_cap",
  "adw_model",
  "exempt_paths",
  "exempt_families",
  "baseline",
  "gates",
  "rule_gates",
  "kill_switches",
  "data_boundary",
] as const;
const LEGACY_FAMILY_KEYS = ["punctuation", "english", "clean_code"] as const;
export const FAMILY_STATES = ["off", "observe", "enforce"] as const;
export const RULE_STATES = ["off", "observe", "enforce", "judged"] as const;
export const BASELINE_MODES = ["git", "report", "none"] as const;

type ConfigValueKey = (typeof CONFIG_VALUE_KEYS)[number];
export type GateState = (typeof FAMILY_STATES)[number];
export type RuleState = (typeof RULE_STATES)[number];
export type BaselineMode = (typeof BASELINE_MODES)[number];

export type AdwBridgeOperation = "describe" | "read" | "validate" | "write";

export interface AdwConfigureRequest {
  operation: AdwBridgeOperation;
  cwd?: string;
  expected_digest?: string | null;
  values?: Record<string, unknown>;
}

export type AdwBridgeResponse = Record<string, unknown>;

export interface AdwFamilyMetadata {
  name: string;
  states: GateState[];
  locked: boolean;
}

export interface AdwRuleMetadata {
  name: string;
  states: RuleState[];
  locked: boolean;
}

export interface AdwRuntimeStatus {
  python: { configured: boolean; executable: string };
  embedding: { configured: boolean };
  embedding_model: { configured: boolean };
}

export interface AdwPolicyState {
  projectPath: string;
  configPath: string;
  digest: string | null;
  exists: boolean;
  values: Record<string, unknown>;
  effective: Record<string, unknown>;
  familyStates: Record<string, GateState>;
  ruleStates: Record<string, RuleState>;
  runtime: AdwRuntimeStatus;
  families: AdwFamilyMetadata[];
  rules: AdwRuleMetadata[];
  alwaysBlockingRules: string[];
}

export type AdwBridgeRunner = (request: AdwConfigureRequest) => AdwBridgeResponse;

/** Represents a bridge failure that can be shown as a bounded notification. */
export class AdwBridgeError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "AdwBridgeError";
    this.code = code;
  }
}

const isRecord = adwConfig.isRecord;

/** Return an identifier-shaped bridge name after control filtering. */
function safeName(value: unknown): string | undefined {
  const text = adwConfig.safePolicyString(value, 128);
  return text && /^[A-Za-z][A-Za-z0-9_.-]*$/.test(text) ? text : undefined;
}

/** Deduplicate bridge names while preserving their response order. */
function uniqueNames(values: unknown): string[] {
  if (!Array.isArray(values)) return [];
  const names: string[] = [];
  for (const value of values) {
    const name = safeName(value);
    if (name && !names.includes(name)) names.push(name);
  }
  return names;
}

/** Parse a supported family gate state from bridge data. */
export function allowedFamilyState(value: unknown): GateState | undefined {
  return typeof value === "string" && (FAMILY_STATES as readonly string[]).includes(value)
    ? (value as GateState)
    : undefined;
}

/** Parse a supported rule gate state from bridge data. */
export function allowedRuleState(value: unknown): RuleState | undefined {
  return typeof value === "string" && (RULE_STATES as readonly string[]).includes(value)
    ? (value as RuleState)
    : undefined;
}

/** Parse a supported baseline mode from bridge data. */
export function allowedBaseline(value: unknown): BaselineMode | undefined {
  return typeof value === "string" && (BASELINE_MODES as readonly string[]).includes(value)
    ? (value as BaselineMode)
    : undefined;
}

/** Collect valid family names advertised by metadata or state maps. */
function readFamilyNames(response: Record<string, unknown>): string[] {
  const metadata = Array.isArray(response.families)
    ? response.families
        .filter(isRecord)
        .map(item => item.name)
        .filter((name): name is string => safeName(name) !== undefined)
    : [];
  const stateNames = isRecord(response.family_states) ? Object.keys(response.family_states) : [];
  return uniqueNames([...metadata, ...stateNames]);
}

/** Collect valid rule names advertised by metadata or state maps. */
function readRuleNames(response: Record<string, unknown>): string[] {
  const metadata = Array.isArray(response.rules)
    ? response.rules
        .filter(isRecord)
        .map(item => item.name)
        .filter((name): name is string => safeName(name) !== undefined)
    : [];
  const stateNames = isRecord(response.rule_states) ? Object.keys(response.rule_states) : [];
  return uniqueNames([...metadata, ...stateNames]);
}

/** Build editable family metadata with safe defaults for incomplete responses. */
function readFamilyMetadata(response: Record<string, unknown>, names: readonly string[]): AdwFamilyMetadata[] {
  const source = Array.isArray(response.families) ? response.families.filter(isRecord) : [];
  return names.map(name => {
    const metadata = source.find(item => item.name === name);
    const states = Array.isArray(metadata?.states)
      ? metadata.states.filter((state): state is GateState => allowedFamilyState(state) !== undefined)
      : [...FAMILY_STATES];
    return { name, states: states.length > 0 ? [...new Set(states)] : [...FAMILY_STATES], locked: metadata?.locked === true };
  });
}

/** Build rule metadata and force always-blocking rules to enforce. */
function readRuleMetadata(response: Record<string, unknown>, names: readonly string[]): AdwRuleMetadata[] {
  const source = Array.isArray(response.rules) ? response.rules.filter(isRecord) : [];
  return names.map(name => {
    const metadata = source.find(item => item.name === name);
    const locked = metadata?.locked === true || (Array.isArray(response.always_blocking_rules) && response.always_blocking_rules.includes(name));
    const states = locked
      ? ["enforce"]
      : Array.isArray(metadata?.states)
        ? metadata.states.filter((state): state is RuleState => allowedRuleState(state) !== undefined)
        : [...RULE_STATES];
    return { name, states: states.length > 0 ? [...new Set(states)] : locked ? ["enforce"] : [...RULE_STATES], locked };
  });
}

/** Filter a bridge state map to the names supported by the response. */
function readStateMap(
  source: unknown,
  names: readonly string[],
  parser: (value: unknown) => GateState | RuleState | undefined,
): Record<string, GateState | RuleState> {
  const input = isRecord(source) ? source : {};
  const output: Record<string, GateState | RuleState> = {};
  for (const name of names) {
    const value = parser(input[name]);
    if (value !== undefined) output[name] = value;
  }
  return output;
}

/** Copy recognized policy values while discarding unsupported or unsafe data. */
function copyKnownValues(
  source: unknown,
  familyNames: readonly string[],
  ruleNames: readonly string[],
): Record<string, unknown> {
  const input = isRecord(source) ? source : {};
  const output: Record<string, unknown> = {};
  for (const key of CONFIG_VALUE_KEYS) {
    if (!(key in input)) continue;
    const value = input[key];
    if ((LEGACY_FAMILY_KEYS as readonly string[]).includes(key)) {
      if (typeof value === "boolean") output[key] = value;
      continue;
    }
    if (["max_rows", "sentence_word_cap", "list_item_cap"].includes(key)) {
      if (typeof value === "number" && Number.isSafeInteger(value)) output[key] = value;
      continue;
    }
    if (key === "adw_model") {
      if (typeof value === "string" && value.length <= 256 && !/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/.test(value)) {
        output[key] = value;
      }
      continue;
    }
    if (key === "baseline") {
      const baseline = allowedBaseline(value);
      if (baseline !== undefined) output[key] = baseline;
      continue;
    }
    if (key === "exempt_paths") {
      if (Array.isArray(value)) {
        output[key] = value
          .map(item => adwConfig.safePolicyString(item))
          .filter((item): item is string => item !== undefined);
      }
      continue;
    }
    if (key === "exempt_families") {
      const mappings = isRecord(value) ? value : {};
      const filtered: Record<string, string[]> = {};
      for (const [pattern, families] of Object.entries(mappings)) {
        const safePattern = adwConfig.safePolicyString(pattern);
        if (!safePattern || !Array.isArray(families)) continue;
        const selected = families.filter(
          (family): family is string => typeof family === "string" && familyNames.includes(family),
        );
        filtered[safePattern] = selected;
      }
      output[key] = filtered;
      continue;
    }
    if (key === "gates") {
      const gates = readStateMap(value, familyNames, allowedFamilyState);
      output[key] = gates;
      continue;
    }
    if (key === "rule_gates") {
      output[key] = readStateMap(value, ruleNames, allowedRuleState);
      continue;
    }
    if (key === "kill_switches") {
      const switches = isRecord(value) ? value : {};
      const filtered: Record<string, boolean> = {};
      for (const family of familyNames) {
        if (typeof switches[family] === "boolean") filtered[family] = switches[family] as boolean;
      }
      output[key] = filtered;
      continue;
    }
    if (key === "data_boundary") {
      const boundary = isRecord(value) ? value : {};
      if (typeof boundary.enabled === "boolean") output[key] = { enabled: boundary.enabled };
      continue;
    }
  }
  return output;
}

/** Redact runtime details to a safe executable basename and status flags. */
function readRuntime(response: Record<string, unknown>): AdwRuntimeStatus {
  const runtime = isRecord(response.runtime) ? response.runtime : {};
  const python = isRecord(runtime.python) ? runtime.python : {};
  const embedding = isRecord(runtime.embedding) ? runtime.embedding : {};
  const model = isRecord(runtime.embedding_model) ? runtime.embedding_model : {};
  const executable = adwConfig.safePolicyString(python.executable, 128) ?? "";
  return {
    python: {
      configured: python.configured === true,
      executable: executable ? basename(executable.replaceAll("\\", "/")) : "",
    },
    embedding: { configured: embedding.configured === true },
    embedding_model: { configured: model.configured === true },
  };
}

/** Convert a bridge read response into the known, display-safe editor state. */
export function decodeAdwPolicy(response: unknown): AdwPolicyState {
  if (!isRecord(response) || response.ok !== true) {
    const error = isRecord(response) && isRecord(response.error) ? response.error : {};
    const code = adwConfig.sanitizeDisplay(error.code, 64) || "bridge_failure";
    const message = adwConfig.sanitizeDisplay(error.message, 240) || "ADW configuration bridge failed";
    throw new AdwBridgeError(code, message);
  }
  const familyNames = readFamilyNames(response);
  const ruleNames = readRuleNames(response);
  const digest = response.digest === null ? null : adwConfig.safePolicyString(response.digest, 64);
  if (digest !== null && (!digest || !/^[0-9a-f]{64}$/.test(digest))) {
    throw new AdwBridgeError("invalid_response", "ADW bridge returned an invalid project digest");
  }
  const alwaysBlockingRules = uniqueNames(response.always_blocking_rules).filter(name => ruleNames.includes(name));
  const ruleStates = readStateMap(response.rule_states, ruleNames, allowedRuleState) as Record<string, RuleState>;
  for (const rule of alwaysBlockingRules) ruleStates[rule] = "enforce";
  return {
    projectPath: adwConfig.sanitizeDisplay(response.project_path, 1024),
    configPath: adwConfig.sanitizeDisplay(response.config_path, 1024),
    digest,
    exists: response.exists === true,
    values: copyKnownValues(response.values, familyNames, ruleNames),
    effective: copyKnownValues(response.effective, familyNames, ruleNames),
    familyStates: readStateMap(response.family_states, familyNames, allowedFamilyState) as Record<string, GateState>,
    ruleStates,
    runtime: readRuntime(response),
    families: readFamilyMetadata(response, familyNames),
    rules: readRuleMetadata(response, ruleNames),
    alwaysBlockingRules,
  };
}

/** Turn a bridge response error into a bounded message safe for notifications. */
export function bridgeResponseError(response: unknown): AdwBridgeError | undefined {
  if (!isRecord(response) || response.ok === true) return undefined;
  const error = isRecord(response.error) ? response.error : {};
  return new AdwBridgeError(
    adwConfig.sanitizeDisplay(error.code, 64) || "bridge_failure",
    adwConfig.sanitizeDisplay(error.message, 240) || "ADW configuration bridge failed",
  );
}

/** Decode one bounded JSON response from the bridge process. */
function parseBridgeOutput(output: string | Buffer): AdwBridgeResponse {
  const bytes = Buffer.isBuffer(output) ? output : Buffer.from(output, "utf8");
  if (bytes.byteLength > BRIDGE_MAX_OUTPUT_BYTES) {
    throw new AdwBridgeError("response_limit", "ADW configuration bridge response is too large");
  }
  let value: unknown;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw new AdwBridgeError("invalid_response", "ADW configuration bridge returned invalid JSON");
  }
  if (!isRecord(value)) throw new AdwBridgeError("invalid_response", "ADW configuration bridge returned an invalid response");
  return value;
}

function createCapability(): { directory: string; path: string; token: string } {
  const directory = mkdtempSync(join(tmpdir(), "adw-config-"));
/** Create a one-shot capability file with restrictive permissions. */
  const path = join(directory, "capability");
  const token = randomBytes(32).toString("hex");
  if (Buffer.byteLength(token, "utf8") > CAPABILITY_MAX_BYTES) {
    rmSync(directory, { recursive: true, force: true });
    throw new AdwBridgeError("capability_required", "ADW configuration capability could not be created");
  }
  writeFileSync(path, token, { encoding: "utf8", flag: "wx", mode: 0o600 });
  return { directory, path, token };
}

/** Create a bridge runner that uses the fixed Configure route and one-shot write capability. */
export function createConfigureBridgeRunner(runnerPath = resolveRunner()): AdwBridgeRunner {
  return request => {
    const environment: NodeJS.ProcessEnv = { ...process.env };
    delete environment.ADW_CONFIG_CAPABILITY;
    delete environment.ADW_CONFIG_CAPABILITY_FILE;
    let capability: { directory: string; path: string; token: string } | undefined;
    if (request.operation === "write") {
      capability = createCapability();
      environment.ADW_CONFIG_CAPABILITY = capability.token;
      environment.ADW_CONFIG_CAPABILITY_FILE = capability.path;
    }
    try {
      const output = execFileSync(runnerPath, ["Configure"], {
        input: JSON.stringify(request),
        encoding: "utf8",
        env: environment,
        maxBuffer: BRIDGE_MAX_OUTPUT_BYTES,
        timeout: BRIDGE_TIMEOUT_MS,
      });
      return parseBridgeOutput(output);
    } catch (error) {
      if (error instanceof AdwBridgeError) throw error;
      const stdout = isRecord(error) ? error.stdout : undefined;
      if (typeof stdout === "string" || Buffer.isBuffer(stdout)) {
        try {
          return parseBridgeOutput(stdout);
        } catch {
          // The process error is intentionally reduced to a fixed message below.
        }
      }
      throw new AdwBridgeError("bridge_failure", "ADW configuration bridge could not complete");
    } finally {
      if (capability) rmSync(capability.directory, { recursive: true, force: true });
    }
  };
}

/** Run one bounded bridge request using the installed ADW runner. */
export function runConfigureBridge(request: AdwConfigureRequest): AdwBridgeResponse {
  return createConfigureBridgeRunner()(request);
}
