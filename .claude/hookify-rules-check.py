"""Verify the hookify rules in this directory against the real hookify hook scripts."""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile

HOME = os.path.expanduser("~")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plugin_root() -> str:
    hits = glob.glob(os.path.join(HOME, ".claude/plugins/cache/*/hookify/*/hooks/pretooluse.py"))
    if not hits:
        raise SystemExit("hookify plugin not installed")
    return os.path.dirname(os.path.dirname(sorted(hits)[0]))


PLUGIN = plugin_root()


def run(script: str, payload: dict) -> tuple[dict, str]:
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=PLUGIN)
    proc = subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "hooks", script)],
        input=json.dumps(payload), capture_output=True, text=True, cwd=REPO, env=env,
        check=False,
    )
    return json.loads(proc.stdout or "{}"), proc.stderr


def verdict(result: dict) -> str:
    if not result:
        return "allow"
    if result.get("decision") == "block":
        return "block"
    if result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
        return "block"
    return "warn"


def tool_case(tool: str, tool_input: dict) -> tuple[str, dict]:
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    return "pretooluse.py", payload


def bash_case(command: str) -> tuple[str, dict]:
    return tool_case("Bash", {"command": command})


def transcript(text: str) -> tuple[str, dict]:
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    handle.write(text)
    handle.close()
    return "stop.py", {"hook_event_name": "Stop", "transcript_path": handle.name}


def tool_use(name: str, tool_input: dict) -> str:
    block = {"type": "tool_use", "id": "toolu_x", "name": name, "input": tool_input}
    line = {"type": "assistant", "message": {"content": [block]}}
    return json.dumps(line, separators=(",", ":"))


HOOK_PY = REPO + "/hooks/stop.py"
EDIT_HOOK = tool_use("Edit", {"file_path": HOOK_PY, "old_string": "a", "new_string": "b"})
WRITE_HOOK = tool_use("Write", {"file_path": REPO + "/hooks/lib/scanner.py", "content": "x"})
READ_HOOK = tool_use("Read", {"file_path": HOOK_PY})
GREP_HOOK = tool_use("Grep", {"pattern": "def main", "path": "hooks/stop.py"})
EDIT_DOCS = tool_use("Edit", {"file_path": REPO + "/README.md", "old_string": "a", "new_string": "b"})
RAN_PYTEST = tool_use("Bash", {"command": "cd hooks && python3 -m pytest . lib -q"})
TOUCHED = json.dumps({"tool": "Edit", "file_path": REPO + "/hooks/stop.py"})
CASES = [
    ("live claude settings", tool_case("Write", {"file_path": HOME + "/.claude/settings.json", "content": "{}"}), "block"),
    ("live claude skill link", tool_case("Write", {"file_path": HOME + "/.claude/skills/adw/SKILL.md", "content": "x"}), "block"),
    ("live codex config", tool_case("Edit", {"file_path": HOME + "/.codex/config.toml", "new_string": "x"}), "block"),
    ("live opencode plugin", tool_case("Write", {"file_path": HOME + "/.config/opencode/plugins/x.ts", "content": "x"}), "block"),
    ("job scratch write", tool_case("Write", {"file_path": HOME + "/.claude/jobs/a/tmp/x.py", "content": "x"}), "allow"),
    ("memory write", tool_case("Write", {"file_path": HOME + "/.claude/projects/p/memory/x.md", "content": "x"}), "allow"),
    ("read of live settings", tool_case("Read", {"file_path": HOME + "/.claude/settings.json"}), "allow"),
    ("repo hookify rule write", tool_case("Write", {"file_path": REPO + "/.claude/hookify.x.local.md", "content": "x"}), "allow"),
    ("repo snippet edit", tool_case("Edit", {"file_path": REPO + "/hooks/claude-settings.snippet.json", "new_string": "{}"}), "warn"),
    ("repo run.sh edit", tool_case("Edit", {"file_path": REPO + "/hooks/run.sh", "new_string": "x"}), "warn"),
    ("project config edit", tool_case("Write", {"file_path": REPO + "/.agent-discipline.json", "content": "{}"}), "block"),
    ("unrelated source edit", tool_case("Edit", {"file_path": REPO + "/hooks/lib/scanner.py", "new_string": "x"}), "allow"),
    ("live installer", bash_case("./install.sh -y"), "block"),
    ("sandboxed installer", bash_case('HOME="$(mktemp -d)" ./install.sh -y'), "allow"),
    ("live merge script", bash_case("python3 hooks/merge-claude-settings.py --help"), "block"),
    ("sandboxed merge script", bash_case("HOME=/tmp/box python3 hooks/merge-claude-settings.py --help"), "allow"),
    ("installer after separator", bash_case("cd repo && ./install.sh -y"), "block"),
    ("installer named in a string", bash_case("grep -n install.sh README.md"), "allow"),
    ("installer syntax check", bash_case("bash -n install.sh hooks/run.sh"), "allow"),
    ("installer in a git pathspec", bash_case("git log --oneline -- install.sh"), "allow"),
    ("no-verify commit", bash_case("git commit --no-verify -m 'fix(x): y'"), "block"),
    ("short no-verify commit", bash_case("git commit -n -m 'fix(x): y'"), "block"),
    ("git log with -n", bash_case("git log -n 5 --oneline"), "allow"),
    ("cap override", bash_case("CLEANCODER_FUNC_BLOCK_LINES=500 python3 -m pytest -q"), "block"),
    ("state deletion", bash_case("rm -rf ~/.agent-discipline"), "block"),
    ("conventional commit", bash_case("git commit -m 'E3-S1 feat(hooks): add gate (E3-S1-T1)'"), "allow"),
    ("plan commit", bash_case("git commit -m 'docs(plan): close E3-S1-T2 at-file gate'"), "allow"),
    ("quality commit", bash_case("git commit -m 'Q1 fix(scanner): name the config dotfiles'"), "allow"),
    ("heredoc commit", bash_case('git commit -m "$(cat <<EOF\nfeat: x\nEOF\n)"'), "allow"),
    ("loose commit", bash_case("git commit -m 'update stuff'"), "warn"),
    ("test run", bash_case("cd hooks && python3 -m pytest . lib -q"), "allow"),
    ("redirect into settings", bash_case("echo '{}' > ~/.claude/settings.json"), "block"),
    ("tee into codex config", bash_case("cat x | tee $HOME/.codex/config.toml"), "block"),
    ("sed in place on settings", bash_case("sed -i '' s/a/b/ " + HOME + "/.pi/agent/settings.json"), "block"),
    ("relink live skill", bash_case("ln -snf . ~/.agents/skills/agent-discipline-watcher"), "block"),
    ("read live settings", bash_case("python3 -m json.tool ~/.claude/settings.json"), "allow"),
    ("grep live settings", bash_case("grep -n run.sh ~/.claude/settings.json"), "allow"),
    ("repo redirect", bash_case("echo x > hooks/claude-settings.snippet.json"), "allow"),
    ("stderr null to protected", bash_case("cat ~/.claude/settings.json 2>/dev/null"), "allow"),
    ("stderr dup to protected", bash_case("python3 -m json.tool ~/.claude/settings.json 2>&1 | head"), "allow"),
    ("stderr append to protected", bash_case("grep x ~/.codex/config.toml 2>>/tmp/err.log"), "allow"),
    ("write plus stderr to protected", bash_case("echo '{}' > ~/.claude/settings.json 2>/dev/null"), "block"),
    ("append redirect to protected", bash_case("echo x >> ~/.codex/config.toml"), "block"),
    ("stdout fd redirect to protected", bash_case("echo x 1> ~/.claude/settings.json"), "block"),
    ("dd onto protected", bash_case("dd if=/tmp/x of=$HOME/.pi/agent/settings.json"), "block"),
    ("stop after hook edit", transcript(EDIT_HOOK), "block"),
    ("stop after hook write", transcript(WRITE_HOOK), "block"),
    ("stop after hook edit and tests", transcript(EDIT_HOOK + "\n" + RAN_PYTEST), "allow"),
    ("stop after hook read only", transcript(READ_HOOK), "allow"),
    ("stop after hook grep only", transcript(GREP_HOOK), "allow"),
    ("stop after docs edit plus hook read", transcript(EDIT_DOCS + "\n" + READ_HOOK), "allow"),
    ("stop after docs only", transcript(EDIT_DOCS), "allow"),
    ("stop after prose mention of hook path", transcript(json.dumps({"text": "see hooks/stop.py for the gate"})), "allow"),
    ("stop on empty transcript", transcript(""), "allow"),
]


def main() -> int:
    failures = 0
    for label, (script, payload), expected in CASES:
        result, err = run(script, payload)
        got = verdict(result)
        if got != expected:
            failures += 1
        status = "FAIL" if got != expected else "ok  "
        print(f"{status} {label:30s} expected={expected:5s} got={got}")
        if err.strip():
            print("      stderr: " + err.strip().replace("\n", " | ")[:200])
    print(f"\n{len(CASES) - failures} of {len(CASES)} cases matched")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
