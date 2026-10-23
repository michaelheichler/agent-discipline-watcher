import { afterAll, afterEach, beforeAll, expect, test } from "bun:test";
import type { Api, AssistantMessage, Context, Model } from "@oh-my-pi/pi-ai";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createOmpReviewer, type OmpReviewContext } from "./omp-review";
import { type CompleteSimple } from "./omp-provider";
import { type ReviewBridge } from "./omp-review-bridge";
import { watcherPayload } from "./watcher";

type Call = { system: string; user: string };
const HOOKS = join(import.meta.dir, "..", "..", "..", "hooks");
const MODEL = { provider: "anthropic", id: "claude-haiku", api: "anthropic-messages" } as Model<Api>;
const COMMENT = "Returns the result because the caller needs a value.";
const PARAGRAPH = "The parser reads every record before the report runs, and the report lists each record once.";
const directories: string[] = [];
const EMBEDDING_SWITCH = "ADW_EMBEDDING_DISABLED";
const hostSwitch = process.env[EMBEDDING_SWITCH];

// Off, because an enabled host makes each document prepare wait for the model.
beforeAll(() => {
  process.env[EMBEDDING_SWITCH] = "1";
});

// Restored, because every Bun test file shares this process environment.
afterAll(() => {
  if (hostSwitch === undefined) delete process.env[EMBEDDING_SWITCH];
  else process.env[EMBEDDING_SWITCH] = hostSwitch;
});

afterEach(() => {
  for (const directory of directories.splice(0)) rmSync(directory, { recursive: true, force: true });
});

// Same interpreter as the bridge, so the reference cannot drift.
function python(code: string, ...args: string[]): string {
  const floor = readFileSync(join(HOOKS, "..", ".python-version"), "utf8").trim();
  const resolve = '. "$1/resolve-python.sh" && adw_resolve_python "$2"';
  const interpreter = execFileSync("sh", ["-c", resolve, "sh", HOOKS, floor], { encoding: "utf8" }).trim();
  return execFileSync(interpreter, ["-E", "-S", "-c", code, ...args], { cwd: HOOKS, encoding: "utf8" });
}

function sharedInstructions(cwd: string): string {
  return python(
    "import sys\nfrom lib import judge_contracts\nfrom lib.config import effective_hook_config\n" +
    "sys.stdout.write(judge_contracts.reviewer_instructions(effective_hook_config({}, sys.argv[1])))",
    cwd,
  );
}

function rubrics(): string[] {
  return JSON.parse(python(
    "import json\nfrom lib import judge_contracts as j\nfrom lib.document_review import HUNK_NOTICE\n" +
    "print(json.dumps([j.COMMENT_RUBRIC, j.PATTERN_RUBRIC, j.GERMAN_PATTERN_RUBRIC, j.DOCUMENT_RUBRIC, j.LANGUAGE_RUBRIC, HUNK_NOTICE]))",
  )) as string[];
}

// Off the default cap, because a bridge ignoring project config must differ.
function project(file: string, text: string): string {
  const cwd = realpathSync(mkdtempSync(join(tmpdir(), "adw-omp-prompt-")));
  directories.push(cwd);
  const listItemCap = Number(python("from lib.config import DEFAULTS\nprint(DEFAULTS['list_item_cap'])")) + 1;
  writeFileSync(join(cwd, ".agent-discipline.json"), JSON.stringify({
    data_boundary: { enabled: true }, adw_model: "anthropic/claude-haiku", list_item_cap: listItemCap,
  }));
  writeFileSync(join(cwd, file), text);
  return cwd;
}

function reply(body: unknown): AssistantMessage {
  return { content: [{ type: "text", text: JSON.stringify(body) }], stopReason: "stop" } as AssistantMessage;
}

const COMMENT_REPLY = reply({ items: [{ index: 0, verdict: "states_why", reason: "Names a constraint." }] });
const DOCUMENT_REPLY = reply({ notes: [] });

function reviewContext(cwd: string): OmpReviewContext {
  return {
    cwd, model: MODEL,
    models: { list: () => [MODEL], current: () => MODEL, resolve: () => MODEL },
    modelRegistry: { getApiKey: async () => "session-key", resolver: () => "session-key" },
    sessionManager: { getSessionId: () => "omp-prompt" },
  } as unknown as OmpReviewContext;
}

async function review(cwd: string, file: string, answer: AssistantMessage): Promise<Call[]> {
  const calls: Call[] = [];
  const complete = (async (_model: Model<Api>, context: Context) => {
    const user = context.messages[0]?.content;
    calls.push({ system: (context.systemPrompt ?? []).join("\n"), user: typeof user === "string" ? user : JSON.stringify(user) });
    return answer;
  }) as unknown as CompleteSimple;
  await createOmpReviewer({ complete })(reviewContext(cwd), watcherPayload(cwd, "omp-prompt", "Write", { file_path: join(cwd, file) }));
  return calls;
}

function bridgeWith(instructions: Record<string, unknown>): ReviewBridge {
  const request = { id: 0, prompt: "Judge each line.\n0. A line.", schema: {}, ...instructions };
  return call => call.operation === "prepare"
    ? { enabled: true, model: "anthropic/claude-haiku", path: "a.py", digest: "d", requests: [request] }
    : {};
}

function occurrences(text: string, part: string): number {
  return text.split(part).length - 1;
}

test("the OMP reviewer sends the shared reviewer instructions once, in its system prompt", async () => {
  const cwd = project("source.py", `# ${COMMENT}\n`);
  const block = sharedInstructions(cwd);

  const calls = await review(cwd, "source.py", COMMENT_REPLY);

  expect(calls.map(call => [occurrences(call.system, block), occurrences(call.user, block)])).toEqual([[1, 0]]);
});

test.each([
  ["source.py", `# ${COMMENT}\n`, COMMENT_REPLY],
  ["guide.md", `${PARAGRAPH}\n`, DOCUMENT_REPLY],
])("the OMP reviewer states no rubric twice in one call reviewing %s", async (file, text, answer) => {
  const cwd = project(file, text);
  const known = rubrics();

  const calls = await review(cwd, file, answer);

  const repeated = calls.flatMap(call => known.filter(rubric => occurrences(`${call.system}\n${call.user}`, rubric) > 1));
  expect({ sent: calls.length > 0, repeated }).toEqual({ sent: true, repeated: [] });
});

test("the OMP reviewer still sends the candidate text in the user message", async () => {
  const cwd = project("source.py", `# ${COMMENT}\n`);

  const calls = await review(cwd, "source.py", COMMENT_REPLY);

  expect(calls.map(call => call.user.includes(COMMENT))).toEqual([true]);
});

test.each([
  ["carries instructions", { instructions: "Judge only the supplied text." }, { calls: 1, blocked: false }],
  ["omits instructions", {}, { calls: 0, blocked: true }],
  ["carries empty instructions", { instructions: "" }, { calls: 0, blocked: true }],
])("a prepared request that %s reaches the model only when instructions are present", async (_name, instructions, expected) => {
  let calls = 0;
  const complete = (async () => { calls += 1; return COMMENT_REPLY; }) as unknown as CompleteSimple;
  const reviewer = createOmpReviewer({ bridge: bridgeWith(instructions), complete });

  const result = await reviewer(reviewContext(tmpdir()), { tool_name: "Write" });

  expect({ calls, blocked: result.decision === "block" }).toEqual(expected);
});
