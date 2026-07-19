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

const PY_SCAN = `
import json
import sys
from pathlib import Path

root = Path(sys.argv[2])
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "hooks"))

target = sys.argv[1]
text = Path(target).read_text(errors="replace")
config = {"punctuation": True, "english": True, "clean_code": True}

try:
    from hooks.lib.scanner import scan_all
except Exception:
    from lib.scanner import scan_all

print(json.dumps(scan_all(target, text, config) or []))
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
  force?: boolean;
};

function editedPath(event: any): string | undefined {
  return event?.input?.path ?? event?.input?.file_path ?? event?.input?.filename ?? event?.result?.path;
}

function isWriteTool(name: unknown): boolean {
  const tool = String(name ?? "").toLowerCase();
  return tool === "write" || tool === "edit" || tool === "multiedit";
}

async function scan(file: string): Promise<Finding[]> {
  try {
    const { stdout } = await run("python3", ["-c", PY_SCAN, file, ROOT], {
      timeout: 30000,
      env: { ...process.env, PYTHONPATH: `${ROOT}${path.delimiter}${path.join(ROOT, "hooks")}` },
      maxBuffer: 1024 * 1024,
    });
    const findings = JSON.parse(stdout || "[]");
    return Array.isArray(findings) ? findings : [];
  } catch {
    return [];
  }
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

export default function (pi: any) {
  pi.on("before_agent_start", async (event: any) => {
    return { systemPrompt: `${event?.systemPrompt ?? ""}\n\n${POLICY}` };
  });

  pi.on("tool_result", async (event: any) => {
    if (!isWriteTool(event?.toolName)) return undefined;
    const file = editedPath(event);
    if (!file) return undefined;
    const findings = await scan(file);
    const forced = findings.filter((finding) => finding.force !== false);
    if (forced.length) {
      const message = compactReport(forced.map((finding) => ({ file, finding })));
      return { content: [{ type: "text", text: message }], isError: true };
    }
    return undefined;
  });
}
