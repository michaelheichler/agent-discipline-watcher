import { Buffer } from "node:buffer";

const MAX_EDIT_SECTIONS = 32;
const MAX_EDIT_BYTES = 64 * 1024;
const SECTION_RE = /^\[([^#\]]+)#[^\]]+\]\s*$/;
const MOVE_RE = /^MV\s+(.+)$/;
const QUOTE_RE = /^["']|["']$/g;

export type HashlineEdit = {
  path: string;
  added: string;
};

// Undefined, because a partial decode would under-scan.
export type HashlineDecode = HashlineEdit[] | undefined;

export function hashlineEdits(patch: unknown): HashlineDecode {
  if (typeof patch !== "string" || patch.length === 0) {
    return [];
  }
  if (Buffer.byteLength(patch, "utf8") > MAX_EDIT_BYTES) {
    return undefined;
  }
  const added = new Map<string, string[]>();
  const order: string[] = [];
  let current: string | undefined;
  let overflowed = false;

  const claim = (target: string): boolean => {
    if (!target) {
      return false;
    }
    if (!added.has(target)) {
      if (order.length >= MAX_EDIT_SECTIONS) {
        overflowed = true;
        return false;
      }
      added.set(target, []);
      order.push(target);
    }
    return true;
  };

  for (const line of patch.split("\n")) {
    const header = SECTION_RE.exec(line);
    if (header) {
      const target = (header[1] ?? "").trim().replace(QUOTE_RE, "");
      current = claim(target) ? target : undefined;
      continue;
    }
    const move = MOVE_RE.exec(line);
    if (move) {
      claim((move[1] ?? "").trim().replace(QUOTE_RE, ""));
      continue;
    }
    if (current === undefined || !line.startsWith("+")) {
      continue;
    }
    added.get(current)?.push(line.slice(1));
  }

  if (overflowed) {
    return undefined;
  }
  return order.map(path => ({ path, added: (added.get(path) ?? []).join("\n") }));
}

export function hashlinePatchSource(input: Record<string, unknown> | undefined): unknown {
  if (!input) {
    return undefined;
  }
  for (const key of ["input", "patch"] as const) {
    const value = input[key];
    if (typeof value === "string") {
      return value;
    }
  }
  return undefined;
}
