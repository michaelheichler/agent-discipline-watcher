import { afterEach, beforeEach, expect, test } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createExtension } from "./index";
import { VerificationLedger } from "./lifecycle";
import type { WatcherResult } from "./watcher";

type Handler = (event: unknown, ctx: unknown) => Promise<unknown>;
type SentMessage = { content: string; display: boolean };
type StopResult = { decision?: string; reason?: string } | undefined;

const BLOCKED_FIVE_TIMES = ["block", "block", "block", "block", "block"];
const RELEASED_ON_SIXTH = [...BLOCKED_FIVE_TIMES, undefined];

const roots: string[] = [];
let savedHome: string | undefined;
let testHome = "";

beforeEach(() => {
  savedHome = process.env.HOME;
  testHome = mkdtempSync(join(tmpdir(), "adw-release-home-"));
  roots.push(testHome);
  process.env.HOME = testHome;
});

afterEach(() => {
  process.env.HOME = savedHome;
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function harness(run: (event: string) => WatcherResult = () => ({})) {
  const cwd = mkdtempSync(join(tmpdir(), "adw-release-"));
  roots.push(cwd);
  const handlers = new Map<string, Handler>();
  const sent: SentMessage[] = [];
  const context = { cwd, sessionManager: { getSessionId: () => cwd } };
  const pi = {
    on: (name: string, handler: Handler) => handlers.set(name, handler),
    registerCommand() {},
    async sendMessage(message: SentMessage) { sent.push(message); },
  };
  createExtension(pi as never, event => run(event), undefined, async () => ({}));
  const call = (name: string, event: unknown) => handlers.get(name)?.(event, context);
  return {
    cwd,
    call,
    visible: () => sent.filter(message => message.display),
    sentCount: () => sent.length,
    undecodable: (toolCallId: string, toolName = "edit") =>
      call("tool_result", { toolName, toolCallId, input: { path: "a.md", file_path: "b.md" }, content: [] }),
    stops: async (count: number) => {
      const decisions: (string | undefined)[] = [];
      for (let index = 0; index < count; index++) decisions.push(((await call("session_stop", {})) as StopResult)?.decision);
      return decisions;
    },
  };
}

function ledgerRows(): Record<string, unknown>[] {
  const file = join(testHome, ".adw", "ledger", "ledger.jsonl");
  if (!existsSync(file)) return [];
  return readFileSync(file, "utf-8").trim().split("\n").map(line => JSON.parse(line));
}

test("blocks the first five Stops after an unresolved tool result", async () => {
  const h = harness();
  await h.undecodable("call-alpha");

  expect(await h.stops(5)).toEqual(BLOCKED_FIVE_TIMES);
});

test("leaves the sixth identical Stop open", async () => {
  const h = harness();
  await h.undecodable("call-alpha");
  await h.stops(5);

  expect(((await h.call("session_stop", {})) as StopResult)?.decision).toBeUndefined();
});

test("tells the user on release which tool calls stayed unverified", async () => {
  const h = harness();
  await h.undecodable("call-alpha", "edit");
  await h.undecodable("call-beta", "notebook");

  await h.stops(6);

  const notices = h.visible();
  expect(notices).toHaveLength(1);
  expect(notices[0].content).toContain("edit");
  expect(notices[0].content).toContain("call-alpha");
  expect(notices[0].content).toContain("notebook");
  expect(notices[0].content).toContain("call-beta");
});

test("records one stop_stall release row for the unresolved target", async () => {
  const h = harness();
  await h.undecodable("call-alpha");

  await h.stops(6);

  expect(ledgerRows()).toEqual([
    expect.objectContaining({ rule: "stop_stall", family: "own_finding", path: VerificationLedger.UNKNOWN_TARGET }),
  ]);
});

test("stays open and silent on the Stop after a release", async () => {
  const h = harness();
  await h.undecodable("call-alpha");
  await h.stops(6);
  const sentBefore = h.sentCount();

  const decision = ((await h.call("session_stop", {})) as StopResult)?.decision;

  expect({ decision, newMessages: h.sentCount() - sentBefore, rows: ledgerRows().length }).toEqual({
    decision: undefined, newMessages: 0, rows: 1,
  });
});

test("blocks five Stops again for a new unresolved call after a release", async () => {
  const h = harness();
  await h.undecodable("call-alpha");
  await h.stops(6);
  await h.undecodable("call-beta");

  expect(await h.stops(6)).toEqual(RELEASED_ON_SIXTH);
});

test("restarts the Stop count when a second unresolved call arrives before the release", async () => {
  const h = harness();
  await h.undecodable("call-alpha");
  await h.stops(3);
  await h.undecodable("call-beta");

  expect(await h.stops(6)).toEqual(RELEASED_ON_SIXTH);
});

test("leaves Stop open once a later result for the same call resolves its file", async () => {
  const h = harness();
  const target = join(h.cwd, "note.md");
  writeFileSync(target, "A short note.\n");
  await h.undecodable("call-alpha", "write");
  await h.call("tool_result", { toolName: "write", toolCallId: "call-alpha", input: { path: target, content: "A short note.\n" }, content: [] });

  expect(((await h.call("session_stop", {})) as StopResult)?.decision).toBeUndefined();
});

function blockedFileHarness() {
  const state = { fileBlocked: true };
  const reason = "note.md still has an open finding";
  const h = harness(event => (event === "PostToolUse" && state.fileBlocked ? { decision: "block", reason } : {}));
  const target = join(h.cwd, "note.md");
  writeFileSync(target, "A short note.\n");
  return { h, state, reason, target };
}

test("keeps blocking on a pending file when the unresolved entry is released", async () => {
  const { h, reason, target } = blockedFileHarness();
  await h.call("tool_result", { toolName: "write", toolCallId: "file-call", input: { path: target, content: "A short note.\n" }, content: [] });
  await h.undecodable("call-alpha");
  await h.stops(5);

  const result = (await h.call("session_stop", {})) as StopResult;

  expect({ decision: result?.decision, reason: result?.reason, notices: h.visible().length }).toEqual({
    decision: "block", reason: expect.stringContaining(reason), notices: 1,
  });
});

test("leaves Stop open after a release once the pending file passes", async () => {
  const { h, state, target } = blockedFileHarness();
  await h.call("tool_result", { toolName: "write", toolCallId: "file-call", input: { path: target, content: "A short note.\n" }, content: [] });
  await h.undecodable("call-alpha");
  await h.stops(6);
  state.fileBlocked = false;

  expect(((await h.call("session_stop", {})) as StopResult)?.decision).toBeUndefined();
});
