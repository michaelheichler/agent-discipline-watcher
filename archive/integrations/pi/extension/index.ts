import { execFile } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);

const ROOT = path.resolve(__dirname, "../../..");

const POLICY = [
  "Agent Discipline Watcher is active.",
  "Keep punctuation plain, prose direct, and code free of narration, dead code, and task marker comments.",
  "Use commas, periods, or parentheses instead of banned dash marks or double hyphen breaks.",
  "Use plain words and make every sentence earn its place.",
  "Let code names carry intent. Comments explain only hidden reasons.",
].join(" ");

export function stripFrontmatter(skill: string): string {
  const delimiter = "-".repeat(3);
  const lines = skill.split("\n");
  if (lines[0] !== delimiter) return skill;
  const end = lines.indexOf(delimiter, 1);
  return end < 0 ? "" : lines.slice(end + 1).join("\n");
}

export function readableOutputRules(): string {
  try {
    const skill = fs.readFileSync(path.join(ROOT, "skills", "readable-output", "SKILL.md"), "utf8");
    const body = stripFrontmatter(skill).trim();
    return body ? `READABLE OUTPUT RULES ACTIVE (main agent only)\n\n${body}` : "";
  } catch {
    return "";
  }
}

const MAIN_AGENT_POLICY = [POLICY, readableOutputRules()].filter(Boolean).join("\n\n");

const PY_SCAN = `
import json
import sys
from pathlib import Path

root = Path(sys.argv[2])
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "hooks"))

target = sys.argv[1]
project_cwd = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
text = Path(target).read_text(errors="replace")

try:
    from hooks.lib.config import effective_config
    from hooks.lib.scanner import scan_all
except Exception:
    from lib.config import effective_config
    from lib.scanner import scan_all

print(json.dumps(scan_all(target, text, effective_config(None, project_cwd)) or []))
`;

type Finding = {
  path?: string;
  file?: string;
  line?: number;
  rule?: string;
  family?: string;
  action?: string;
  detail?: string;
  fix?: string;
  next_code?: string;
};

type PiEvent = {
  systemPrompt?: string;
  toolName?: unknown;
  cwd?: string;
  input?: { path?: string; file_path?: string; filename?: string; cwd?: string };
  result?: { path?: string };
};

type PiHost = { on(name: string, handler: (event: PiEvent) => Promise<unknown>): void };

class ScanFailure extends Error {}

function editedPath(event: PiEvent): string | undefined {
  return event?.input?.path ?? event?.input?.file_path ?? event?.input?.filename ?? event?.result?.path;
}

function projectCwd(event: PiEvent, file: string): string {
  return event?.input?.cwd ?? event?.cwd ?? path.dirname(file);
}

function isWriteTool(name: unknown): boolean {
  const tool = String(name ?? "").toLowerCase();
  return tool === "write" || tool === "edit" || tool === "multiedit";
}

function failureText(failure: unknown): string {
  if (failure && typeof failure === "object") {
    const record = failure as { stderr?: unknown; message?: unknown };
    return String(record.stderr || record.message || "scanner did not run");
  }
  return String(failure ?? "scanner did not run");
}

async function scan(file: string, cwd: string): Promise<Finding[]> {
  let stdout = "";
  try {
    ({ stdout } = await run("python3", ["-c", PY_SCAN, file, ROOT, cwd], {
      timeout: 30000,
      env: { ...process.env, PYTHONPATH: `${ROOT}${path.delimiter}${path.join(ROOT, "hooks")}` },
      maxBuffer: 1024 * 1024,
    }));
  } catch (failure: unknown) {
    throw new ScanFailure(failureText(failure));
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout || "[]");
  } catch {
    throw new ScanFailure(`scanner returned non JSON output: ${short(stdout, "empty")}`);
  }
  if (!Array.isArray(parsed)) throw new ScanFailure("scanner returned a non list result");
  return parsed as Finding[];
}

function short(text: unknown, fallback: string): string {
  const value = String(text ?? fallback).replace(/\s+/g, " ").trim();
  if (value.length <= 120) return value;
  return `${value.slice(0, 117).trim()}...`;
}

function reportPath(rows: Array<{ file: string; finding: Finding }>): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "agent-discipline-watcher-"));
  const file = path.join(dir, "findings.json");
  fs.writeFileSync(file, JSON.stringify(rows, null, 2), { mode: 0o600 });
  fs.chmodSync(file, 0o600);
  return file;
}

function compactReport(rows: Array<{ file: string; finding: Finding }>): string {
  const shown = rows.slice(0, 8);
  const full = reportPath(rows);
  const lines = ["Agent Discipline Watcher found edits to fix before finishing:"];
  for (const row of shown) {
    const finding = row.finding;
    const line = Number.isFinite(finding.line) ? finding.line : 1;
    const family = short(finding.family, "policy");
    const rule = short(finding.rule, "check");
    const action = short(finding.action ?? finding.next_code ?? finding.fix ?? finding.detail, "fix this finding");
    lines.push(`${row.file}:${line} [${family}/${rule}] ${action}`);
  }
  if (rows.length > shown.length) lines.push(`${rows.length - shown.length} more findings in ${full}`);
  else lines.push(`Full report: ${full}`);
  lines.push("Re edit the files, then finish.");
  return lines.join("\n");
}

export default function (pi: PiHost) {
  pi.on("before_agent_start", async (event: PiEvent) => {
    return { systemPrompt: `${event?.systemPrompt ?? ""}\n\n${MAIN_AGENT_POLICY}` };
  });

  pi.on("tool_result", async (event: PiEvent) => {
    if (!isWriteTool(event?.toolName)) return undefined;
    const file = editedPath(event);
    if (!file) return undefined;
    let findings: Finding[];
    try {
      findings = await scan(file, projectCwd(event, file));
    } catch (failure: unknown) {
      // Fails closed like the OpenCode adapter, because an unusable scanner must not read as a clean file.
      const reason = failureText(failure);
      return {
        content: [{ type: "text", text: `Agent Discipline Watcher could not scan ${file}: ${reason}` }],
        isError: true,
      };
    }
    if (findings.length) {
      const message = compactReport(findings.map((finding) => ({ file, finding })));
      return { content: [{ type: "text", text: message }], isError: true };
    }
    return undefined;
  });
}
