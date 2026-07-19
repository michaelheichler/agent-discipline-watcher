import { describe, expect, test } from "bun:test";
import {
	createHooks,
	isWriteTool,
	normalizeArgs,
	resolveRunner,
	type WatcherResult,
} from "./agent-discipline-watcher";

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
				return event === "Stop" ? { decision: "block", reason: "repair touched files" } : {};
			},
		});

		await hooks.event({ event: { type: "session.created", properties: { info: { id: "s1" } } } });
		await hooks.event({ event: { type: "session.idle", properties: { sessionID: "s1" } } });
		await hooks.event({ event: { type: "session.idle", properties: { sessionID: "s1" } } });

		expect(events).toEqual(["SessionStart", "Stop", "Stop"]);
		expect(prompts).toHaveLength(1);
	});
});
