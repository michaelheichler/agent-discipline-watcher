import { describe, expect, test } from "bun:test";
import {
  adaptPythonEvent,
  adaptToolCall,
  adaptToolResult,
  mutationKind,
} from "./tool-adapter";

describe("OMP tool adapter", () => {
  test("classifies the exact native report device without a filesystem target", () => {
    const event = {
      toolName: "write",
      input: { path: "xd://report_issue", content: "write: report route was rejected" },
    };
    const expected = {
      kind: "host-report",
      hookToolName: "Write",
      input: event.input,
      requiresTarget: false,
    };
    expect(adaptToolCall(event)).toEqual(expected);
    expect(adaptToolResult(event)).toEqual(expected);
  });

  test.each([
    { path: "xd://report_issue", content: 1 },
    { path: "xd://report_issue" },
    { file_path: "xd://report_issue", content: "write: rejected" },
    { path: "xd://report_issue", filePath: "xd://report_issue", content: "write: rejected" },
    { path: "xd://report_issue/", content: "write: rejected" },
    { path: "xd://report_issue?next=write", content: "write: rejected" },
    { path: "xd://write", content: "{}" },
  ])("keeps noncanonical report inputs under file validation: %j", input => {
    expect(mutationKind("write", input)).toBe("write");
  });

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

  test("observes unsupported eval languages without a target requirement", () => {
    expect(adaptToolCall({
      toolName: "eval",
      toolCallId: "call-ruby",
      input: { language: "ruby", code: "File.write('a.md', 'body')" },
    })).toEqual({
      kind: "observed",
      hookToolName: "eval",
      input: { language: "ruby", code: "File.write('a.md', 'body')" },
      requiresTarget: false,
    });
  });

  test("observes arbitrary eval JavaScript without parsing its source", () => {
    const inputs = [
      { language: "js", code: "while (true) { await tool.write({path: target, content: body}); }" },
      { language: "javascript", code: "await tool[toolName]({path: computedPath, content: body});" },
      { language: "js", code: "import fs from 'node:fs'; fs.writeFileSync('a.md', 'body');" },
      { language: "javascript", code: "process.exit()" },
    ];
    for (const input of inputs) {
      const event = { toolName: "eval", toolCallId: "call-js", input };
      const expected = {
        kind: "observed",
        hookToolName: "eval",
        input,
        requiresTarget: false,
      };
      expect(adaptToolCall(event)).toEqual(expected);
      expect(adaptToolResult(event)).toEqual(expected);
    }
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

  test("observes context notebook replacement without a target requirement", () => {
    expect(adaptToolCall({
      toolName: "context_notes",
      toolCallId: "call-context-write",
      input: { text: "replace the notebook" },
    })).toEqual({
      kind: "observed",
      hookToolName: "context_notes",
      input: { text: "replace the notebook" },
      requiresTarget: false,
    });
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

  test("observes an unknown tool that declares a write operation without a target", () => {
    expect(adaptToolCall({
      toolName: "custom_writer",
      toolCallId: "call-4",
      input: { operation: "write", path: "a.md", content: "body" },
    })).toEqual({
      kind: "observed",
      hookToolName: "custom_writer",
      input: { operation: "write", path: "a.md", content: "body" },
      requiresTarget: false,
    });
  });

  test("observes unknown command and mutation shapes without a target", () => {
    expect(mutationKind("custom_runner", { command: "printf body > a.md" })).toBe("observed");
    expect(mutationKind("custom_writer", { destination: "a.md", payload: "body" })).toBe("observed");
  });

  test("observes hub tools without requiring a target or rejection reason", () => {
    expect(adaptToolCall({
      toolName: "hub",
      toolCallId: "hub-1",
      input: { operation: "write", destination: "a.md", payload: "body" },
    })).toEqual({
      kind: "observed",
      hookToolName: "hub",
      input: { operation: "write", destination: "a.md", payload: "body" },
      requiresTarget: false,
    });
  });

  test("allows only documented read-only LSP and debug actions", () => {
    expect(mutationKind("lsp", { action: "hover" })).toBe("other");
    expect(mutationKind("lsp", { action: "rename_file" })).toBe("observed");
    expect(mutationKind("debug", { action: "threads" })).toBe("other");
    expect(mutationKind("debug", { action: "continue" })).toBe("observed");
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

  test.each([
    "append_file", "create_file", "delete_file", "edit_file", "move_file", "patch_file",
    "remove_file", "rename_file", "update_file", "write_file", "writeFile", "batch_write_files",
  ])("tracks a path-only MCP %s mutation", name => {
    expect(adaptToolCall({
      toolName: `mcp__fs__${name}`,
      input: { path: "a.md" },
    })).toMatchObject({ kind: "mcp", requiresTarget: true, targetPaths: ["a.md"] });
  });

  test.each(["delete_file", "removeFile"])("retains delete intent from MCP %s without an operation field", name => {
    expect(adaptToolCall({
      toolName: `mcp__fs__${name}`,
      input: { path: "a.md" },
    }).deletedTargetPaths).toEqual(["a.md"]);
  });

  test.each([
    "list_write_requests", "get_delete_history", "read_update_log", "getWriteStatus", "batch_list_write_requests",
  ])("keeps the MCP query %s outside mutation coverage", name => {
    expect(adaptToolCall({
      toolName: `mcp__fs__${name}`,
      input: { path: "a.md" },
    })).toMatchObject({ kind: "other", requiresTarget: false });
  });

  test.each(["write_file", "batch_write_files", "delete_file"])("does not let a read operation disguise MCP %s", name => {
    expect(adaptToolCall({
      toolName: `mcp__fs__${name}`,
      input: { path: "a.md", operation: "read" },
    })).toMatchObject({ kind: "mcp", requiresTarget: true, targetPaths: ["a.md"] });
  });

  test("does not use the MCP server name as a mutation signal", () => {
    expect(mutationKind("mcp__write_server__read_file", { path: "a.md" })).toBe("other");
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
