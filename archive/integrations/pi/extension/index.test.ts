import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import register, { readableOutputRules, stripFrontmatter } from "./index";

type Event = {
  systemPrompt?: string;
  toolName?: unknown;
  cwd?: string;
  input?: { path?: string; file_path?: string; filename?: string; cwd?: string };
  result?: { path?: string };
};

type Handler = (event: Event) => Promise<unknown>;

const temporaryDirectories: string[] = [];

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

function temporaryFile(content: string): string {
  const directory = mkdtempSync(join(tmpdir(), "adw-pi-test-"));
  temporaryDirectories.push(directory);
  const file = join(directory, "target.ts");
  writeFileSync(file, content);
  return file;
}

function registered(name: string): Handler {
  const handlers = new Map<string, Handler>();
  register({ on(eventName, handler) { handlers.set(eventName, handler); } });
  const handler = handlers.get(name);
  if (!handler) throw new Error(`missing ${name} handler`);
  return handler;
}

describe("Pi readable output helpers", () => {
  test("strips complete frontmatter only", () => {
    const fence = "-".repeat(3);
    expect(stripFrontmatter(`${fence}\nname: test\n${fence}\n# Body\n`)).toBe("# Body\n");
    expect(stripFrontmatter("# Body\n")).toBe("# Body\n");
    expect(stripFrontmatter(`${fence}\nname: test\n`)).toBe("");
  });

  test("loads the readable output body without metadata", () => {
    const rules = readableOutputRules();
    expect(rules).toStartWith("READABLE OUTPUT RULES ACTIVE (main agent only)");
    expect(rules).toContain("# Readable Output");
    expect(rules).not.toContain("name: readable-output");
  });
});

describe("Pi prompt handler", () => {
  test("appends policy and readable rules before the agent starts", async () => {
    const result = await registered("before_agent_start")({ systemPrompt: "Existing prompt" }) as {
      systemPrompt: string;
    };
    expect(result.systemPrompt).toStartWith("Existing prompt");
    expect(result.systemPrompt).toContain("Agent Discipline Watcher is active.");
    expect(result.systemPrompt).toContain("READABLE OUTPUT RULES ACTIVE (main agent only)");
  });
});

describe("Pi scan handler", () => {
  test("ignores read-only tools", async () => {
    expect(await registered("tool_result")({ toolName: "read" })).toBeUndefined();
  });

  test("returns nothing for a clean write", async () => {
    const file = temporaryFile("export const value = 1;\n");
    expect(await registered("tool_result")({ toolName: "write", input: { path: file } })).toBeUndefined();
  });

  test("returns scanner findings as an error", async () => {
    const badDash = String.fromCharCode(0x2014);
    const file = temporaryFile(`export const value = "bad${badDash}text";\n`);
    const result = await registered("tool_result")({ toolName: "edit", input: { path: file } }) as {
      content: Array<{ text: string }>;
      isError: boolean;
    };
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toContain("punctuation/banned_dash");
    const report = result.content[0].text.match(/Full report: (.+)$/m)?.[1];
    if (report) rmSync(dirname(report), { recursive: true, force: true });
  });

  test("fails closed when the scanner cannot read the target", async () => {
    const file = temporaryFile("export const value = 1;\n");
    rmSync(file);
    const result = await registered("tool_result")({ toolName: "write", input: { path: file } });
    expect(result).toMatchObject({ isError: true });
    expect(result).toHaveProperty("content.0.text", expect.stringContaining("could not scan"));
  });
});
