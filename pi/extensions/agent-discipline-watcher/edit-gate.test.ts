import { describe, expect, test } from "bun:test";

import { hashlineEdits, hashlinePatchSource } from "./hashline";
import { preGatePayloads, selectableModels } from "./index";

const TEST_CWD = process.cwd();
const ctx = {
  cwd: TEST_CWD,
  sessionManager: { getSessionId: () => "s1" },
};

describe("model selection from the host catalogue", () => {
  test("offers every model the catalogue returns, whatever the vendor", () => {
    const offered = selectableModels([
      { provider: "anthropic", id: "claude-haiku-4-5" },
      { provider: "anthropic", id: "claude-sonnet-5" },
      { provider: "openai-codex", id: "gpt-5.6" },
      { provider: "zai", id: "glm-5.3" },
    ]);

    expect(offered).toEqual(["claude-haiku-4-5", "claude-sonnet-5", "gpt-5.6", "glm-5.3"]);
  });

  test("drops an id that would not survive display sanitising", () => {
    const control = `claude${String.fromCharCode(7)}haiku`;
    const offered = selectableModels([
      { provider: "anthropic", id: control },
      { provider: "anthropic", id: "claude-haiku-4-5" },
      { provider: "anthropic", id: "a".repeat(300) },
    ]);

    expect(offered).toEqual(["claude-haiku-4-5"]);
  });

  test("caps the list so a hostile catalogue cannot flood the picker", () => {
    const many = Array.from({ length: 400 }, (_, index) => ({
      provider: "anthropic",
      id: `model-${index}`,
    }));

    expect(selectableModels(many)).toHaveLength(256);
  });
});

describe("hashline patch decoding", () => {
  test("collects one target and its added text", () => {
    expect(hashlineEdits("[src/a.ts#A1B2]\nPUT 1.=1:\n+const a = 1\n+const b = 2\n")).toEqual([
      { path: "src/a.ts", added: "const a = 1\nconst b = 2" },
    ]);
  });

  test("splits added text per target and keeps move destinations", () => {
    const patch = "[src/a.ts#A1B2]\nPUT 1.=1:\n+alpha\n[lib/b.ts#C3D4]\nPUT 2.=2:\n+beta\nMV lib/c.ts";
    expect(hashlineEdits(patch)).toEqual([
      { path: "src/a.ts", added: "alpha" },
      { path: "lib/b.ts", added: "beta" },
      { path: "lib/c.ts", added: "" },
    ]);
  });

  test("keeps a literal leading plus after stripping the row marker", () => {
    expect(hashlineEdits("[a.md#A1B2]\nPUT 1.=1:\n++ item\n+- item\n")).toEqual([
      { path: "a.md", added: "+ item\n- item" },
    ]);
  });

  test("returns no targets for a foreign patch dialect", () => {
    expect(hashlineEdits("*** Add File: a.py\n+x = 1\n")).toEqual([]);
    expect(hashlineEdits("")).toEqual([]);
    expect(hashlineEdits(undefined)).toEqual([]);
  });

  test("refuses to decode a patch past its byte budget", () => {
    expect(hashlineEdits(`[a.md#A1B2]\nPUT 1.=1:\n+${"x".repeat(65 * 1024)}\n`)).toBeUndefined();
  });

  test("refuses to decode more sections than the budget allows", () => {
    const patch = Array.from({ length: 33 }, (_value, index) => `[f${index}.md#A1B2]\nPUT 1.=1:\n+x`).join("\n");
    expect(hashlineEdits(patch)).toBeUndefined();
  });

  test("reads the patch from the input or patch field only", () => {
    expect(hashlinePatchSource({ input: "one" })).toBe("one");
    expect(hashlinePatchSource({ patch: "two" })).toBe("two");
    expect(hashlinePatchSource({ command: "rm -rf /" })).toBeUndefined();
    expect(hashlinePatchSource({ content: "body" })).toBeUndefined();
    expect(hashlinePatchSource(undefined)).toBeUndefined();
  });
});

describe("pre-gate payloads", () => {
  const event = {
    toolName: "edit",
    toolCallId: "call-1",
    input: { input: "[src/a.ts#A1B2]\nPUT 1.=1:\n+const a = 1\n" },
  };

  test("sends a resolved file_path and the added text per target", () => {
    const sections = hashlineEdits(hashlinePatchSource(event.input));
    if (sections === undefined) throw new Error("expected a decoded patch");

    expect(preGatePayloads(ctx, event, sections)).toEqual([
      {
        cwd: TEST_CWD,
        session_id: "s1",
        tool_name: "Edit",
        tool_use_id: "call-1",
        tool_input: { file_path: `${TEST_CWD}/src/a.ts`, new_string: "const a = 1" },
      },
    ]);
  });

  test("emits one payload per target so every file is scanned", () => {
    const sections = hashlineEdits("[src/a.ts#A1B2]\nPUT 1.=1:\n+alpha\n[lib/b.ts#C3D4]\nPUT 1.=1:\n+beta\n");
    if (sections === undefined) throw new Error("expected a decoded patch");
    const payloads = preGatePayloads(ctx, event, sections);

    expect(payloads.map(payload => payload.tool_input)).toEqual([
      { file_path: `${TEST_CWD}/src/a.ts`, new_string: "alpha" },
      { file_path: `${TEST_CWD}/lib/b.ts`, new_string: "beta" },
    ]);
  });

  test("refuses a target outside the session directory", () => {
    expect(() => preGatePayloads(ctx, event, [{ path: "../outside.ts", added: "x" }])).toThrow(
      "could not resolve an edit target",
    );
  });

  test("falls back to the raw tool input when no target is named", () => {
    const writeEvent = {
      toolName: "write",
      input: { path: "a.md", content: "body" },
    };

    expect(preGatePayloads(ctx, writeEvent, [])).toEqual([
      {
        cwd: TEST_CWD,
        session_id: "s1",
        tool_name: "Write",
        tool_input: { file_path: `${TEST_CWD}/a.md`, content: "body" },
      },
    ]);
  });
});
