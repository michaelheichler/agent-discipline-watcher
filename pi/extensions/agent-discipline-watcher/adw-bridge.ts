/** Because policy belongs to Python, the TUI shares this transport boundary. */
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
const MAX_POLICY_DEPTH = 12;
const MAX_POLICY_ENTRIES = 4096;
export type GateState = string;
export type RuleState = string;
export type RuleSurface = string;
export type RuleGate = RuleState | Partial<Record<RuleSurface, RuleState>>;
export type BaselineMode = string;

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
  ruleStates: Record<string, RuleGate>;
  runtime: AdwRuntimeStatus;
  families: AdwFamilyMetadata[];
  rules: AdwRuleMetadata[];
  alwaysBlockingRules: string[];
  baselineModes: string[];
}

export type AdwBridgeRunner = (request: AdwConfigureRequest) => AdwBridgeResponse;

/** Because notifications need stable failure codes. */
export class AdwBridgeError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "AdwBridgeError";
    this.code = code;
  }
}

const isRecord = adwConfig.isRecord;

/** Because identifiers must not carry terminal controls. */
function safeName(value: unknown): string | undefined {
  const text = adwConfig.safePolicyString(value, 128);
  return text && /^[A-Za-z][A-Za-z0-9_.-]*$/.test(text) ? text : undefined;
}

/** Because repeated metadata must not duplicate editor rows. */
function uniqueNames(values: unknown): string[] {
  if (!Array.isArray(values)) return [];
  const names: string[] = [];
  for (const value of values) {
    const name = safeName(value);
    if (name && !names.includes(name)) names.push(name);
  }
  return names;
}

/** Because Python owns policy, accept safe state identifiers. */
export function allowedFamilyState(value: unknown): GateState | undefined {
  return safeName(value);
}

export const allowedRuleState = allowedFamilyState;
export const allowedBaseline = allowedFamilyState;

/** Because surface names belong to Python, preserve each safe state entry. */
export function allowedRuleGate(value: unknown): RuleGate | undefined {
  const single = allowedRuleState(value);
  if (single !== undefined || !isRecord(value)) return single;
  const surfaces: Partial<Record<RuleSurface, RuleState>> = {};
  for (const [surface, rawState] of Object.entries(value)) {
    const state = allowedRuleState(rawState);
    if (!safeName(surface) || state === undefined) return undefined;
    surfaces[surface] = state;
  }
  return Object.keys(surfaces).length > 0 ? surfaces : undefined;
}

/** Because inherited families can appear only in state maps. */
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

/** Because inherited rules can appear only in state maps. */
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

/** Because Python advertises the editable family states. */
function readFamilyMetadata(response: Record<string, unknown>, names: readonly string[]): AdwFamilyMetadata[] {
  const source = Array.isArray(response.families) ? response.families.filter(isRecord) : [];
  return names.map(name => {
    const metadata = source.find(item => item.name === name);
    return { name, states: uniqueNames(metadata?.states), locked: metadata?.locked === true };
  });
}

/** Because protected rules must stay locked in the editor. */
function readRuleMetadata(response: Record<string, unknown>, names: readonly string[]): AdwRuleMetadata[] {
  const source = Array.isArray(response.rules) ? response.rules.filter(isRecord) : [];
  return names.map(name => {
    const metadata = source.find(item => item.name === name);
    const locked = metadata?.locked === true || (Array.isArray(response.always_blocking_rules) && response.always_blocking_rules.includes(name));
    return { name, states: uniqueNames(metadata?.states), locked };
  });
}

/** Known names only, so an unknown rule never reaches the editor. */
function readStateMap<State>(
  source: unknown,
  names: readonly string[],
  parser: (value: unknown) => State | undefined,
): Record<string, State> {
  const input = isRecord(source) ? source : {};
  const output: Record<string, State> = {};
  for (const name of names) {
    const value = parser(input[name]);
    if (value !== undefined) output[name] = value;
  }
  return output;
}

/** Because Python validates policy, preserve bounded JSON values. */
function copyPolicyValue(value: unknown, depth: number, budget: { remaining: number }): unknown {
  budget.remaining -= 1;
  if (depth > MAX_POLICY_DEPTH || budget.remaining < 0) {
    throw new AdwBridgeError("response_limit", "ADW policy exceeds the transport limit");
  }
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.length <= BRIDGE_MAX_OUTPUT_BYTES &&
      !/[\u0000-\u001f\u007f-\u009f‪-‮⁦-⁩]/u.test(value)) return value;
  if (Array.isArray(value)) return value.map(item => copyPolicyValue(item, depth + 1, budget));
  if (isRecord(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => {
      if (!adwConfig.safePolicyString(key, 4096)) {
        throw new AdwBridgeError("invalid_response", "ADW policy contains an unsafe key");
      }
      return [key, copyPolicyValue(item, depth + 1, budget)];
    }));
  }
  throw new AdwBridgeError("invalid_response", "ADW policy contains invalid transport data");
}

function copyPolicyValues(source: unknown): Record<string, unknown> {
  if (!isRecord(source)) return {};
  const copied = copyPolicyValue(source, 0, { remaining: MAX_POLICY_ENTRIES });
  if (!isRecord(copied)) throw new AdwBridgeError("invalid_response", "ADW policy is not an object");
  return copied;
}

/** Because runtime status must not disclose private paths. */
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

/** Because untrusted bridge data must cross one decoding boundary. */
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
  const ruleStates = readStateMap(response.rule_states, ruleNames, allowedRuleGate);
  for (const rule of alwaysBlockingRules) ruleStates[rule] = "enforce";
  return {
    projectPath: adwConfig.sanitizeDisplay(response.project_path, 1024),
    configPath: adwConfig.sanitizeDisplay(response.config_path, 1024),
    digest,
    exists: response.exists === true,
    values: copyPolicyValues(response.values),
    effective: copyPolicyValues(response.effective),
    familyStates: readStateMap(response.family_states, familyNames, allowedFamilyState),
    ruleStates,
    runtime: readRuntime(response),
    families: readFamilyMetadata(response, familyNames),
    rules: readRuleMetadata(response, ruleNames),
    alwaysBlockingRules,
    baselineModes: isRecord(response.wording) && isRecord(response.wording.baseline_wording)
      ? uniqueNames(Object.keys(response.wording.baseline_wording)) : [],
  };
}

/** Because errors can contain untrusted terminal text. */
export function bridgeResponseError(response: unknown): AdwBridgeError | undefined {
  if (!isRecord(response) || response.ok === true) return undefined;
  const error = isRecord(response.error) ? response.error : {};
  return new AdwBridgeError(
    adwConfig.sanitizeDisplay(error.code, 64) || "bridge_failure",
    adwConfig.sanitizeDisplay(error.message, 240) || "ADW configuration bridge failed",
  );
}

/** Because child output must stay within the transport budget. */
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
/** Because only the interactive editor may authorize policy writes. */
  const path = join(directory, "capability");
  const token = randomBytes(32).toString("hex");
  if (Buffer.byteLength(token, "utf8") > CAPABILITY_MAX_BYTES) {
    rmSync(directory, { recursive: true, force: true });
    throw new AdwBridgeError("capability_required", "ADW configuration capability could not be created");
  }
  writeFileSync(path, token, { encoding: "utf8", flag: "wx", mode: 0o600 });
  return { directory, path, token };
}

/** Because policy writes require a fresh interactive capability. */
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
          const response = parseBridgeOutput(stdout);
          if (response.ok === false && isRecord(response.error) &&
              typeof response.error.code === "string" && typeof response.error.message === "string") {
            return response;
          }
        } catch {
          // Because child errors can expose private process details.
        }
      }
      throw new AdwBridgeError("bridge_failure", "ADW configuration bridge could not complete");
    } finally {
      if (capability) rmSync(capability.directory, { recursive: true, force: true });
    }
  };
}

/** Because every configure request uses the installed gate runtime. */
export function runConfigureBridge(request: AdwConfigureRequest): AdwBridgeResponse {
  return createConfigureBridgeRunner()(request);
}
