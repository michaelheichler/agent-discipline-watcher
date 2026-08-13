import { execFileSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

export type WatcherResult = {
	decision?: string;
	reason?: string;
	systemMessage?: string;
	hookSpecificOutput?: {
		additionalContext?: string;
	};
};

type WatcherEvent = "SessionStart" | "PreToolUse" | "PostToolUse" | "Stop";
type WatcherRun = (event: WatcherEvent, payload: Record<string, unknown>) => WatcherResult;

const WRITE_TOOLS = new Set(["write", "edit"]);

export function isWriteTool(tool: string): boolean {
	return WRITE_TOOLS.has(tool);
}

export function normalizeArgs(args: Record<string, unknown> | undefined): Record<string, unknown> {
	if (!args) return {};
	const normalized: Record<string, unknown> = { ...args };
	const mappings: Array<[string, string]> = [
		["filePath", "file_path"],
		["newString", "new_string"],
		["oldString", "old_string"],
	];
	for (const [source, destination] of mappings) {
		if (source in normalized && !(destination in normalized)) {
			normalized[destination] = normalized[source];
			delete normalized[source];
		}
	}
	return normalized;
}

export function resolveRunner(
	environment: Record<string, string | undefined> = process.env,
	home: string = homedir(),
): string {
	const override = environment.AGENT_DISCIPLINE_WATCHER_HOME;
	const root = override || join(home, ".agents", "skills", "agent-discipline-watcher");
	return join(root, "hooks", "run.sh");
}

export function runWatcher(
	event: WatcherEvent,
	payload: Record<string, unknown>,
	runner: string = resolveRunner(),
): WatcherResult {
	try {
		const output = execFileSync(runner, [event], {
			encoding: "utf-8",
			input: JSON.stringify(payload),
			maxBuffer: 1024 * 1024,
		}).trim();
		return output ? (JSON.parse(output) as WatcherResult) : {};
	} catch (error) {
		const failure = error as { stderr?: string | Buffer; stdout?: string | Buffer; message?: string };
		const stderr = String(failure.stderr ?? "").trim();
		const stdout = String(failure.stdout ?? "").trim();
		return {
			decision: "block",
			reason: stderr || stdout || failure.message || `${event} watcher failed`,
		};
	}
}

type AdapterOptions = {
	directory: string;
	client: {
		session: {
			promptAsync: (input: unknown) => Promise<unknown>;
		};
	};
	run?: WatcherRun;
};

export function createHooks({ directory, client, run = runWatcher }: AdapterOptions) {
	const lastIdleMessage = new Map<string, string>();
	const payload = (
		sessionID: string,
		tool?: string,
		args?: Record<string, unknown>,
	): Record<string, unknown> => ({
		cwd: directory,
		session_id: sessionID,
		...(tool ? { tool_name: tool, tool_input: normalizeArgs(args) } : {}),
	});
	const throwIfBlocked = (result: WatcherResult) => {
		if (result.decision === "block") {
			throw new Error(result.reason || "agent-discipline-watcher blocked the operation");
		}
	};

	return {
		"tool.execute.before": async (
			input: { tool: string; sessionID: string },
			output: { args?: Record<string, unknown> },
		) => {
			if (!isWriteTool(input.tool)) return;
			throwIfBlocked(run("PreToolUse", payload(input.sessionID, input.tool, output.args)));
		},
		"tool.execute.after": async (
			input: { tool: string; sessionID: string; args?: Record<string, unknown> },
			_output: unknown,
		) => {
			if (!isWriteTool(input.tool)) return;
			throwIfBlocked(run("PostToolUse", payload(input.sessionID, input.tool, input.args)));
		},
		async event({ event }: { event: { type: string; properties: Record<string, unknown> } }) {
			if (event.type === "session.created") {
				const info = event.properties.info as { id?: string; parentID?: string } | undefined;
				if (!info?.id || info.parentID) return;
				const result = run("SessionStart", payload(info.id));
				const context = result.hookSpecificOutput?.additionalContext;
				if (context) {
					await client.session.promptAsync({
						sessionID: info.id,
						parts: [{ type: "text", text: `[System: ${context}]` }],
					});
				}
				return;
			}
			if (event.type !== "session.idle") return;
			const sessionID = String(event.properties.sessionID ?? "");
			if (!sessionID) return;
			const result = run("Stop", payload(sessionID));
			const message = result.reason || result.systemMessage || "";
			if (!message || lastIdleMessage.get(sessionID) === message) return;
			lastIdleMessage.set(sessionID, message);
			await client.session.promptAsync({
				sessionID,
				parts: [{ type: "text", text: `[System: ${message}]` }],
			});
		},
	};
}

const AgentDisciplineWatcher = async ({ client, directory }: AdapterOptions) =>
	createHooks({ client, directory });

export default {
	id: "agent-discipline-watcher/opencode",
	server: AgentDisciplineWatcher,
};
