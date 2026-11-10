import { afterAll, afterEach, beforeAll, expect, test } from "bun:test";
import type { Api, AssistantMessage, Context, Model } from "@oh-my-pi/pi-ai";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createOmpReviewer, type OmpReviewContext } from "./omp-review";
import { completeOmpJudge, type CompleteSimple } from "./omp-provider";
import { prepareReview, validatedReview, type ReviewBridge } from "./omp-review-bridge";
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
    state_root: join(cwd, "state"), ledger_root: join(cwd, "ledger"),
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
  const prompt = "Judge each line.\n0. A line.";
  const schema = JSON.parse(python("import json\nfrom lib.judge_contracts import COMMENT_SCHEMA\nprint(json.dumps(COMMENT_SCHEMA))"));
  const request = { id: 0, prompt, schema, ...instructions };
  const digest = createHash("sha256").update(prompt).digest("hex");
  return call => call.operation === "prepare"
    ? { enabled: true, model: "anthropic/claude-haiku", path: join(tmpdir(), "a.py"), digest, requests: [request] }
    : {};
}

function preparedFixture() {
  const schema = JSON.parse(python("import json\nfrom lib.judge_contracts import DOCUMENT_SCHEMA\nprint(json.dumps(DOCUMENT_SCHEMA))"));
  return {
    enabled: true, model: "", path: join(tmpdir(), "adw-review-note.md"), digest: "a".repeat(64),
    requests: [{ id: 0, prompt: "Review text", instructions: "Judge text", schema }],
  };
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

test.each([
  ["source.py", `# ${COMMENT}\n`, COMMENT_REPLY],
  ["guide.md", `${PARAGRAPH}\n`, DOCUMENT_REPLY],
])("the OMP reviewer preserves the shared untrusted boundary for %s", async (file, text, answer) => {
  const cwd = project(file, text);

  const calls = await review(cwd, file, answer);

  expect(calls.map(call => [occurrences(call.user, "<adw-untrusted>"), occurrences(call.user, "</adw-untrusted>")])).toEqual([[1, 1]]);
  expect(calls.map(call => occurrences(call.system, sharedInstructions(cwd)))).toEqual([1]);
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

test("shared document schemas and an empty model selection remain valid preparations", () => {
  const value = preparedFixture();

  const result = prepareReview(value);

  expect(result).toEqual(value);
});

function preparationWithLimit(limit: unknown, type = "array") {
  const value = preparedFixture();
  value.requests[0].schema.properties.notes = type === "array"
    ? { ...value.requests[0].schema.properties.notes, maxItems: limit }
    : { type, maxItems: limit };
  return value;
}

test.each([0, 6, Number.MAX_SAFE_INTEGER])("accepts a safe array maxItems of %s", limit => {
  const value = preparationWithLimit(limit);

  expect(prepareReview(value)).toEqual(value);
});

test.each([-1, 0.5, "6", null, undefined, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])(
  "rejects an invalid array maxItems of %s", limit => {
    const value = preparationWithLimit(limit);

    expect(() => prepareReview(value)).toThrow();
  },
);

test.each(["string", "number", "boolean", "object"])("rejects maxItems on a %s schema", type => {
  const value = preparationWithLimit(6, type);

  expect(() => prepareReview(value)).toThrow();
});

const malformedPreparations = [
  ["empty schema", (value: ReturnType<typeof preparedFixture>) => ({ ...value, requests: [{ ...value.requests[0], schema: {} }] })],
  ["empty path", (value: ReturnType<typeof preparedFixture>) => ({ ...value, path: "" })],
  ["relative path", (value: ReturnType<typeof preparedFixture>) => ({ ...value, path: "note.md" })],
  ["empty digest", (value: ReturnType<typeof preparedFixture>) => ({ ...value, digest: "" })],
  ["short digest", (value: ReturnType<typeof preparedFixture>) => ({ ...value, digest: "d" })],
  ["blank model", (value: ReturnType<typeof preparedFixture>) => ({ ...value, model: " " })],
  ["missing properties", (value: ReturnType<typeof preparedFixture>) => ({ ...value, requests: [{ ...value.requests[0], schema: { ...value.requests[0].schema, properties: [] } }] })],
  ["invalid items", (value: ReturnType<typeof preparedFixture>) => ({ ...value, requests: [{ ...value.requests[0], schema: { type: "object", additionalProperties: false, required: ["notes"], properties: { notes: { type: "array", items: null } } } }] })],
  ["invalid enum", (value: ReturnType<typeof preparedFixture>) => ({ ...value, requests: [{ ...value.requests[0], schema: { type: "object", additionalProperties: false, required: ["status"], properties: { status: { type: "string", enum: [1] } } } }] })],
  ["blank instructions", (value: ReturnType<typeof preparedFixture>) => ({ ...value, requests: [{ ...value.requests[0], instructions: " " }] })],
  ["unknown field", (value: ReturnType<typeof preparedFixture>) => ({ ...value, unexpected: true })],
] as const;

test.each(malformedPreparations)("a preparation with %s cannot reach review", (_name, malformed) => {
  const value = malformed(preparedFixture());

  expect(() => prepareReview(value)).toThrow();
});

test.each([
  { decision: "block", reason: " " },
  { reason: "Something failed" },
  { decision: "block" },
  { systemMessage: [] },
  { unexpected: true },
])("incomplete verdict %j cannot become successful feedback", value => {
  expect(() => validatedReview(value)).toThrow();
});

test.each([{}, { decision: "block", reason: "Repair the source" }, { systemMessage: "Observed finding" }])(
  "complete verdict %j preserves its observable outcome", value => {
    expect(validatedReview(value)).toEqual(value);
  },
);

test.each([null, [], 1, "text"])("non-object bridge preparation %j fails closed before completion", async value => {
  let calls = 0;
  const reviewer = createOmpReviewer({ bridge: () => value, complete: async () => { calls += 1; return COMMENT_REPLY; } });

  const result = await reviewer(reviewContext(tmpdir()), { tool_name: "Write" });

  expect(result.decision).toBe("block");
  expect(calls).toBe(0);
});

test.each([null, [], 1, "text"])("non-object model response %j cannot become document notes", async value => {
  const cwd = project("guide.md", `${PARAGRAPH}\n`);
  let calls = 0;
  const reviewer = createOmpReviewer({ complete: async () => { calls += 1; return reply(value); } });

  const result = await reviewer(reviewContext(cwd), watcherPayload(cwd, "omp-prompt", "Write", { file_path: join(cwd, "guide.md") }));

  expect(result.decision).toBe("block");
  expect(calls).toBe(2);
});

test.each([null, [], 1, "text", true, {}, { enabled: 1 }, { enabled: "true" }, { enabled: false }])(
  "non-consenting boundary %j cannot send source to a model", async dataBoundary => {
    let calls = 0;

    const result = await completeOmpJudge(reviewContext(tmpdir()), { prompt: "Review text", dataBoundary }, async () => { calls += 1; return COMMENT_REPLY; });

    expect(result).toBeUndefined();
    expect(calls).toBe(0);
  },
);

test("exact boolean consent permits one completion", async () => {
  let calls = 0;

  const result = await completeOmpJudge(reviewContext(tmpdir()), { prompt: "Review text", dataBoundary: { enabled: true } }, async () => { calls += 1; return COMMENT_REPLY; });

  expect(result?.model).toBe(MODEL.id);
  expect(calls).toBe(1);
});
