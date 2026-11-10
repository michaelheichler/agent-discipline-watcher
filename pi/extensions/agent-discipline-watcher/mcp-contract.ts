import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { isRecord } from "./adw-config";
import { resolveRunner } from "./watcher";

const MAX_CONTRACT_BYTES = 16 * 1024;
const LIST_FIELDS = ["path_keys", "path_list_keys", "path_tokens", "content_keys", "change_keys", "operation_keys", "write_operations", "delete_operations"] as const;
const LIMIT_FIELDS = ["max_argument_nodes", "max_argument_depth"] as const;
const PATTERN_FIELDS = ["key_acronym_pattern", "key_camel_pattern", "word_pattern"] as const;
type Contract = Record<(typeof LIST_FIELDS)[number], ReadonlySet<string>> &
  Record<(typeof LIMIT_FIELDS)[number], number> & Record<(typeof PATTERN_FIELDS)[number], RegExp> &
  { changes: ReadonlySet<string> };

function loadContract(): Contract | undefined {
  try {
    const source = readFileSync(join(dirname(resolveRunner()), "lib", "mcp_contract.json"));
    if (source.byteLength > MAX_CONTRACT_BYTES) return undefined;
    const value: unknown = JSON.parse(source.toString("utf8"));
    if (!isRecord(value) || Object.keys(value).length !== LIST_FIELDS.length + LIMIT_FIELDS.length + PATTERN_FIELDS.length) return undefined;
    const lists = Object.fromEntries(LIST_FIELDS.map(key => {
      const entries = value[key];
      if (!Array.isArray(entries) || !entries.every((item): item is string => typeof item === "string")) {
        throw new Error("invalid MCP contract");
      }
      return [key, new Set(entries)];
    })) as unknown as Pick<Contract, (typeof LIST_FIELDS)[number]>;
    const limits = Object.fromEntries(LIMIT_FIELDS.map(key => {
      const limit = value[key];
      if (typeof limit !== "number" || !Number.isSafeInteger(limit) || limit <= 0) throw new Error("invalid MCP limit");
      return [key, limit];
    })) as Pick<Contract, (typeof LIMIT_FIELDS)[number]>;
    const patterns = Object.fromEntries(PATTERN_FIELDS.map(key => {
      const pattern = value[key];
      if (typeof pattern !== "string" || !pattern) throw new Error("invalid MCP pattern");
      return [key, new RegExp(pattern, "gu")];
    })) as Pick<Contract, (typeof PATTERN_FIELDS)[number]>;
    return { ...lists, ...limits, ...patterns, changes: new Set([...lists.content_keys, ...lists.change_keys]) };
  } catch {
    // Because an unreadable contract must send the call through Python.
    return undefined;
  }
}

const contract = loadContract();

export { isMcpTool } from "./watcher";

function argumentFields(input: unknown): Array<[string, unknown]> {
  if (!contract) throw new Error("MCP argument contract is missing or invalid");
  const pending: Array<[unknown, number]> = [[input, 0]];
  const fields: Array<[string, unknown]> = [];
  let visited = 0;
  while (pending.length > 0) {
    const current = pending.pop();
    if (!current) break;
    const [value, depth] = current;
    if (++visited > contract.max_argument_nodes || depth > contract.max_argument_depth) throw new Error("MCP arguments exceed the inspection limit");
    if (isRecord(value)) {
      const entries = Object.entries(value);
      if (fields.length + entries.length > contract.max_argument_nodes) throw new Error("MCP arguments exceed the inspection limit");
      fields.push(...entries);
      pending.push(...entries.map(([, item]): [unknown, number] => [item, depth + 1]));
      continue;
    }
    if (!Array.isArray(value)) continue;
    if (value.length > contract.max_argument_nodes) throw new Error("MCP arguments exceed the inspection limit");
    pending.push(...value.map((item): [unknown, number] => [item, depth + 1]));
  }
  return fields;
}

function localPath(value: string): string {
  if (!value.toLowerCase().startsWith("file:")) return value;
  const match = /^file:(?:\/\/([^/]*))?(\/[^?#]*)/iu.exec(value);
  if (!match || (match[1] && match[1].toLowerCase() !== "localhost")) throw new Error("MCP file URI must name an absolute local path");
  return decodeURIComponent(match[2] ?? "");
}

function strings(value: unknown): string[] {
  if (typeof value === "string") return value ? [value] : [];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.length > 0) : [];
}

function argumentSummary(input: Record<string, unknown>): { targets: string[]; contents: string[]; hasChanges: boolean } {
  if (!contract) return { targets: [], contents: [], hasChanges: false };
  const targets: string[] = [];
  const contents: string[] = [];
  let hasChanges = false;
  for (const [key, value] of argumentFields(input)) {
    const split = key.replace(contract.key_acronym_pattern, "$1_$2");
    const tokens = split.replace(contract.key_camel_pattern, "$1_$2").toLowerCase().match(contract.word_pattern) ?? [];
    const normalized = tokens.join("_");
    if (contract.changes.has(normalized)) {
      hasChanges = true;
      if (contract.content_keys.has(normalized)) contents.push(...strings(value));
      continue;
    }
    const pathKey = contract.path_keys.has(normalized) || tokens.some(token => contract.path_tokens.has(token));
    if (pathKey && typeof value === "string" && value) targets.push(value);
    else if (contract.path_list_keys.has(normalized) && Array.isArray(value)) targets.push(...strings(value));
  }
  return { targets: [...new Set(targets.map(localPath))], contents, hasChanges };
}

export function mcpTargetPaths(input: Record<string, unknown>): string[] {
  return argumentSummary(input).targets;
}

export function operationValue(input: Record<string, unknown>): string | undefined {
  if (!contract) throw new Error("MCP argument contract is missing or invalid");
  for (const key of contract.operation_keys) {
    const value = input[key];
    if (typeof value === "string" && value) return value.toLowerCase();
  }
  return undefined;
}

export function mcpOperations(toolName: string, input: Record<string, unknown>): string[] {
  if (!contract) return [];
  const name = toolName.split("__").slice(2).join("__");
  const words = name.replace(contract.key_camel_pattern, "$1_$2").toLowerCase().match(contract.word_pattern) ?? [];
  const named = words.length > 1 && words[0] === "batch" ? words[1] : words[0];
  const explicit = [...contract.operation_keys].map(key => input[key]).find(value => typeof value === "string" && value.trim());
  return [named ?? "", typeof explicit === "string" ? explicit.toLowerCase() : ""];
}

export function inspectMcp(toolName: string, input: Record<string, unknown>): { targets: string[]; contents: string[]; operations: string[]; mutation: boolean; deletes: boolean } {
  const summary = argumentSummary(input);
  const operations = mcpOperations(toolName, input);
  return {
    targets: summary.targets, contents: summary.contents, operations,
    mutation: !contract || operations.some(operation => contract.write_operations.has(operation)) || (summary.targets.length > 0 && summary.hasChanges),
    deletes: Boolean(contract && operations.some(operation => contract.delete_operations.has(operation))),
  };
}

export function mcpIsMutation(toolName: string, input: Record<string, unknown>): boolean {
  if (!contract) return true;
  if (mcpOperations(toolName, input).some(operation => contract.write_operations.has(operation))) return true;
  const summary = argumentSummary(input);
  return summary.targets.length > 0 && summary.hasChanges;
}

export function mcpDeletes(toolName: string, input: Record<string, unknown>): boolean {
  return Boolean(contract && mcpOperations(toolName, input).some(operation => contract.delete_operations.has(operation)));
}
