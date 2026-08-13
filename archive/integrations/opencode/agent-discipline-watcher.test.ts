import { describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
	createHooks,
	isWriteTool,
	normalizeArgs,
	resolveRunner,
	runWatcher,
	type WatcherResult,
} from "./agent-discipline-watcher";

function runScript(body: string): WatcherResult {
	const directory = mkdtempSync(join(tmpdir(), "adw-opencode-test-"));
	const runner = join(directory, "runner.sh");
	writeFileSync(runner, `#!/bin/sh\n${body}\n`, { mode: 0o700 });
	try {
		return runWatcher("SessionStart", {}, runner);
	} finally {
		rmSync(directory, { recursive: true, force: true });
	}
}

describe("OpenCode adapter helpers", () => {
	test("recognizes only OpenCode write-like tools", () => {
		expect(isWriteTool("write")).toBe(true);
		expect(isWriteTool("edit")).toBe(true);
		expect(isWriteTool("read")).toBe(false);
		expect(isWriteTool("bash")).toBe(false);
	});

	test("normalizes OpenCode camelCase write arguments", () => {
		expect(normalizeArgs({ filePath: "a.md", newString: "new", oldString: "old" })).toEqual({
			file_path: "a.md",
			new_string: "new",
			old_string: "old",
		});
	});

	test("resolves an override before the shared skill path", () => {
		expect(resolveRunner({ AGENT_DISCIPLINE_WATCHER_HOME: "/opt/watcher" }, "/home/test")).toBe(
			"/opt/watcher/hooks/run.sh",
		);
		expect(resolveRunner({}, "/home/test")).toBe(
			"/home/test/.agents/skills/agent-discipline-watcher/hooks/run.sh",
		);
	});
});

describe("OpenCode lifecycle mapping", () => {
	test("blocks a write before execution when the watcher denies it", async () => {
		const events: string[] = [];
		const hooks = createHooks({
			directory: "/work",
			client: { session: { promptAsync: async () => undefined } },
			run: (event) => {
				events.push(event);
				return { decision: "block", reason: "fix punctuation" };
			},
		});

		await expect(
			hooks["tool.execute.before"](
				{ tool: "write", sessionID: "s1" },
				{ args: { filePath: "a.md", content: "bad" } },
			),
		).rejects.toThrow("fix punctuation");
		expect(events).toEqual(["PreToolUse"]);
	});

	test("ignores read-only tools", async () => {
		let calls = 0;
		const hooks = createHooks({
			directory: "/work",
			client: { session: { promptAsync: async () => undefined } },
			run: () => {
				calls += 1;
				return {};
			},
		});

		await hooks["tool.execute.before"]({ tool: "read", sessionID: "s1" }, { args: {} });
		expect(calls).toBe(0);
	});

	test("blocks continuation after a write with forced findings", async () => {
		const hooks = createHooks({
			directory: "/work",
			client: { session: { promptAsync: async () => undefined } },
			run: (event) =>
				event === "PostToolUse" ? { decision: "block", reason: "repair file" } : {},
		});

		await expect(
			hooks["tool.execute.after"](
				{ tool: "edit", sessionID: "s1", args: { filePath: "a.md", newString: "bad" } },
				{},
			),
		).rejects.toThrow("repair file");
	});

	test("maps session lifecycle and deduplicates idle messages", async () => {
		const events: string[] = [];
		const prompts: unknown[] = [];
		const hooks = createHooks({
			directory: "/work",
			client: { session: { promptAsync: async (value: unknown) => prompts.push(value) } },
			run: (event): WatcherResult => {
				events.push(event);
				if (event === "SessionStart") {
					return {
						hookSpecificOutput: {
							additionalContext: "READABLE OUTPUT RULES ACTIVE (main agent only)\n\nLead with the next action.",
						},
					};
				}
				return { decision: "block", reason: "repair touched files" };
			},
		});

		await hooks.event({ event: { type: "session.created", properties: { info: { id: "s1" } } } });
		await hooks.event({ event: { type: "session.idle", properties: { sessionID: "s1" } } });
		await hooks.event({ event: { type: "session.idle", properties: { sessionID: "s1" } } });

		expect(events).toEqual(["SessionStart", "Stop", "Stop"]);
		expect(prompts).toHaveLength(2);
		expect(prompts[0]).toEqual({
			sessionID: "s1",
			parts: [{
				type: "text",
				text: "[System: READABLE OUTPUT RULES ACTIVE (main agent only)\n\nLead with the next action.]",
			}],
		});
	});
});

describe("OpenCode runner failures", () => {
	test("prefers stderr from a failed runner", () => {
		expect(runScript("printf 'watcher stderr\\n' >&2\nexit 1")).toEqual({
			decision: "block",
			reason: "watcher stderr",
		});
	});

	test("uses stdout when a failed runner has no stderr", () => {
		expect(runScript("printf 'watcher stdout\\n'\nexit 1")).toEqual({
			decision: "block",
			reason: "watcher stdout",
		});
	});

	test("blocks invalid JSON output", () => {
		const result = runScript("printf 'not-json\\n'");
		expect(result.decision).toBe("block");
		expect(result.reason).toMatch(/JSON|Unexpected|invalid/i);
	});
});

describe("OpenCode child sessions", () => {
	test("does not inject the main-agent context into a child session", async () => {
		let runs = 0;
		let prompts = 0;
		const hooks = createHooks({
			directory: "/work",
			client: { session: { promptAsync: async () => { prompts += 1; } } },
			run: () => { runs += 1; return {}; },
		});

		await hooks.event({
			event: { type: "session.created", properties: { info: { id: "child", parentID: "parent" } } },
		});

		expect(runs).toBe(0);
		expect(prompts).toBe(0);
	});
});
