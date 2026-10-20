import { appendFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export const UNRESOLVED_STOP_LIMIT = 5;
const MAX_LISTED_CALLS = 5;

function listedCalls(calls: readonly string[]): string {
  const shown = calls.slice(0, MAX_LISTED_CALLS).join(", ");
  return calls.length > MAX_LISTED_CALLS ? `${shown} and ${calls.length - MAX_LISTED_CALLS} more` : shown;
}

export function unresolvedReleaseNotice(calls: readonly string[]): string {
  return (
    `agent-discipline-watcher: ${calls.length} tool results without a resolvable file path stayed unverified ` +
    `through ${UNRESOLVED_STOP_LIMIT} identical Stops. Not blocking again. Unverified: ${listedCalls(calls)}.`
  );
}

/** Python stop_stall row shape, so that reports count both hosts. */
export function appendReleaseRow(session: string, target: string): void {
  const row = {
    ts: new Date().toISOString(), session_id: session, hook: "stop", event: "Stop", family: "own_finding",
    rule: "stop_stall", path: target, tool_use_id: "", turn_id: "", outcome: "release", duration_ms: 0,
  };
  try {
    const directory = join(process.env.HOME || homedir(), ".adw", "ledger");
    mkdirSync(directory, { recursive: true });
    appendFileSync(join(directory, "ledger.jsonl"), `${JSON.stringify(row)}\n`, "utf-8");
  } catch (error) {
    process.stderr.write(`agent-discipline-watcher: ledger append failed: ${String(error)}\n`);
  }
}
