import { describe, expect, test } from "bun:test";
import { VerificationLedger } from "./lifecycle";

describe("VerificationLedger", () => {
  test("clears only the target that receives a successful verification", () => {
    const ledger = new VerificationLedger();

    ledger.markPending("session-1", "/tmp/one.md");
    ledger.markPending("session-1", "/tmp/two.md");
    ledger.clearTarget("session-1", "/tmp/one.md");

    expect(ledger.pendingTargets("session-1")).toEqual(["/tmp/two.md"]);
  });

  test("keeps an unresolved target when an unrelated target passes", () => {
    const ledger = new VerificationLedger();

    ledger.markPending("session-1", "/tmp/one.md");
    ledger.clearTarget("session-1", "/tmp/other.md");

    expect(ledger.hasPending("session-1")).toBe(true);
    expect(ledger.pendingTargets("session-1")).toEqual(["/tmp/one.md"]);
  });

  test("retains an unknown target until an explicit session reset", () => {
    const ledger = new VerificationLedger();

    ledger.markUnknown("session-1");
    ledger.clearTarget("session-1", "/tmp/one.md");

    expect(ledger.pendingTargets("session-1")).toEqual([VerificationLedger.UNKNOWN_TARGET]);
    ledger.resetSession("session-1");
    expect(ledger.hasPending("session-1")).toBe(false);
  });

  test("does not record a rejected pre-tool attempt", () => {
    const ledger = new VerificationLedger();

    ledger.rejectTool("session-1", "call-1");

    expect(ledger.hasPending("session-1")).toBe(false);
    expect(ledger.acceptedTool("session-1", "call-1")).toBe(false);
    expect(ledger.rejectedTool("session-1", "call-1")).toBe(true);
    ledger.finishTool("session-1", "call-1");
    expect(ledger.rejectedTool("session-1", "call-1")).toBe(false);
  });

  test("preserves a specific pending reason when a later scan has no reason", () => {
    const ledger = new VerificationLedger();

    ledger.markPending("session-1", "/tmp/one.md", "repair the source");
    ledger.markPending("session-1", "/tmp/one.md");

    expect(ledger.pendingReasons("session-1")).toEqual(["repair the source"]);
  });
});
