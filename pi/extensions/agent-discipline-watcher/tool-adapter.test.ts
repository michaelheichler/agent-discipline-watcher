import { describe, expect, test } from "bun:test";
import {
  adaptPythonEvent,
  adaptToolCall,
  adaptToolResult,
  mutationKind,
} from "./tool-adapter";

describe("OMP tool adapter", () => {
  test("maps eval Python calls to the shared Python hook contract", () => {
    expect(adaptToolCall({
      toolName: "eval",
      toolCallId: "call-1",
      input: { language: "py", code: "from pathlib import Path\nPath('a.md').read_text()" },
    })).toEqual({
      kind: "python",
      hookToolName: "Python",
      input: { code: "from pathlib import Path\nPath('a.md').read_text()" },
      requiresTarget: false,
    });
  });

  test("maps user Python events without treating a read as a file write", () => {
    expect(adaptPythonEvent({
      code: "Path('a.md').read_text()",
      cwd: "/tmp/project",
    })).toEqual({
      kind: "python",
      hookToolName: "Python",
      input: { code: "Path('a.md').read_text()" },
      requiresTarget: false,
    });
  });

  test("leaves Python mutation verdicts to the shared read-only gate", () => {
    const adapted = adaptToolCall({
      toolName: "eval",
      toolCallId: "call-2",
      input: { language: "py", code: "Path('a.md').write_text('body')" },
    });

    expect(adapted).toEqual({
      kind: "python",
      hookToolName: "Python",
      input: { code: "Path('a.md').write_text('body')" },
      requiresTarget: false,
    });
  });

  test("maps the legacy python tool name to the same hook contract", () => {
    expect(adaptToolCall({
      toolName: "python",
      toolCallId: "call-python",
      input: { code: "Path('a.md').read_text()" },
    })).toEqual({
      kind: "python",
      hookToolName: "Python",
      input: { code: "Path('a.md').read_text()" },
      requiresTarget: false,
    });
  });

  test("blocks unsupported eval languages before they can write", () => {
    expect(adaptToolCall({
      toolName: "eval",
      toolCallId: "call-ruby",
      input: { language: "ruby", code: "File.write('a.md', 'body')" },
    }).kind).toBe("unknown-write");
  });

  test("blocks every eval JavaScript call without a read-only proof", () => {
    expect(adaptToolCall({
      toolName: "eval",
      toolCallId: "call-js-read",
      input: { language: "js", code: "fs.readFileSync('a.md', 'utf8')" },
    }).kind).toBe("unknown-write");
    expect(adaptToolCall({
      toolName: "eval",
      toolCallId: "call-js-alias",
      input: { language: "js", code: "fs['writeFileSync']('a.md', 'body')" },
    }).kind).toBe("unknown-write");
  });

  test("maps NotebookEdit using its native target and source fields", () => {
    expect(adaptToolCall({
      toolName: "notebookedit",
      toolCallId: "call-3",
      input: { notebookPath: "notes.ipynb", newSource: "print(1)" },
    })).toEqual({
      kind: "notebook",
      hookToolName: "NotebookEdit",
      input: { file_path: "notes.ipynb", new_string: "print(1)" },
      requiresTarget: true,
      targetPaths: ["notes.ipynb"],
    });
  });

  test("captures native edit delete intent with its accepted target", () => {
    expect(adaptToolCall({
      toolName: "edit",
      toolCallId: "call-native-delete",
      input: { path: "obsolete.md", edits: [{ op: "delete" }] },
    })).toMatchObject({
      kind: "write",
      targetPaths: ["obsolete.md"],
      deletedTargetPaths: ["obsolete.md"],
    });
  });

  test("captures apply-patch delete and move targets", () => {
    expect(adaptToolCall({
      toolName: "apply_patch",
      toolCallId: "call-patch-delete",
      input: {
        input: "*** Begin Patch\n*** Update File: old.md\n*** Move to: new.md\n*** Delete File: gone.md\n*** End Patch",
      },
    })).toMatchObject({
      kind: "write",
      targetPaths: ["old.md", "new.md", "gone.md"],
      deletedTargetPaths: ["old.md", "gone.md"],
    });
  });

  test("maps notebook aliases to the shared NotebookEdit hook", () => {
    expect(adaptToolCall({
      toolName: "write_notebook",
      toolCallId: "call-notebook",
      input: { notebookPath: "notes.ipynb", newSource: "print(1)" },
    }).hookToolName).toBe("NotebookEdit");
  });

  test("keeps an explicitly read notebook operation outside mutation coverage", () => {
    expect(adaptToolCall({
      toolName: "notebook",
      toolCallId: "call-notebook-read",
      input: { path: "notes.ipynb", operation: "read" },
    })).toEqual({
      kind: "read",
      hookToolName: "NotebookEdit",
      input: { file_path: "notes.ipynb", operation: "read" },
      requiresTarget: false,
    });
  });

  test("fails closed for context notebook replacement", () => {
    expect(adaptToolCall({
      toolName: "context_notes",
      toolCallId: "call-context-write",
      input: { text: "replace the notebook" },
    }).kind).toBe("unknown-write");
    expect(adaptToolCall({
      toolName: "context_notes",
      toolCallId: "call-context-read",
      input: {},
    }).kind).toBe("read");
  });

  test("preserves an empty replacement for notebook cell deletion", () => {
    expect(adaptToolCall({
      toolName: "notebookedit",
      toolCallId: "call-delete",
      input: { notebookPath: "notes.ipynb", newSource: "" },
    }).input).toEqual({ file_path: "notes.ipynb", new_string: "" });
  });

  test("keeps read-only tools outside mutation coverage", () => {
    expect(mutationKind("read", {})).toBe("read");
    expect(adaptToolResult({ toolName: "read", input: {}, details: undefined, content: [] })).toEqual({
      kind: "read",
      hookToolName: "read",
      input: {},
      requiresTarget: false,
    });
  });

  test("fails closed for an unknown tool that declares a write operation", () => {
    expect(adaptToolCall({
      toolName: "custom_writer",
      toolCallId: "call-4",
      input: { operation: "write", path: "a.md", content: "body" },
    })).toEqual({
      kind: "unknown-write",
      hookToolName: "custom_writer",
      input: { operation: "write", path: "a.md", content: "body" },
      requiresTarget: true,
      reason: "agent-discipline-watcher could not classify this OMP tool as a safe mutation.",
    });
  });

  test("fails closed for unknown command and mutation shapes", () => {
    expect(mutationKind("custom_runner", { command: "printf body > a.md" })).toBe("unknown-write");
    expect(mutationKind("custom_writer", { destination: "a.md", payload: "body" })).toBe("unknown-write");
  });

  test("allows only documented read-only LSP and debug actions", () => {
    expect(mutationKind("lsp", { action: "hover" })).toBe("other");
    expect(mutationKind("lsp", { action: "rename_file" })).toBe("unknown-write");
    expect(mutationKind("debug", { action: "threads" })).toBe("other");
    expect(mutationKind("debug", { action: "continue" })).toBe("unknown-write");
  });

  test("adapts MCP file writes and deletes for lifecycle scanning", () => {
    expect(adaptToolCall({
      toolName: "mcp__files__write",
      toolCallId: "mcp-write",
      input: { file_path: "a.md", content: "body" },
    })).toMatchObject({
      kind: "mcp",
      requiresTarget: true,
      targetPaths: ["a.md"],
    });
    expect(adaptToolCall({
      toolName: "mcp__files__delete",
      toolCallId: "mcp-delete",
      input: { path: "a.md", operation: "delete" },
    })).toMatchObject({
      kind: "mcp",
      deletedTargetPaths: ["a.md"],
    });
    expect(mutationKind("mcp__files__read", { path: "a.md", operation: "read" })).toBe("other");
  });

  test("uses the injected shared Bash resolver for normal file targets", () => {
    const adapted = adaptToolCall(
      { toolName: "bash", toolCallId: "bash-write", input: { command: "printf body > a.md" } },
      (_toolName, input) => (input.command === "printf body > a.md" ? ["a.md"] : []),
    );
    expect(adapted).toMatchObject({ kind: "bash", targetPaths: ["a.md"] });
  });

  test("splits native per-entry edits into pre-gate payloads", () => {
    expect(adaptToolCall({
      toolName: "multiedit",
      toolCallId: "multi-entry",
      input: { edits: [{ path: "a.md", new_string: "a" }, { path: "b.md", newString: "b" }] },
    })).toMatchObject({
      targetPaths: ["a.md", "b.md"],
      preGateInputs: [
        { file_path: "a.md", new_string: "a" },
        { file_path: "b.md", new_string: "b" },
      ],
    });
  });
});
