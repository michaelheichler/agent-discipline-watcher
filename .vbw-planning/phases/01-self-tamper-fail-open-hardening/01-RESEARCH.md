---
phase: 1
title: Self-Tamper & Fail-Open Hardening
type: research
confidence: high
date: 2026-08-05
---

## Findings

All seven items were checked against the current tree, not memory, and, where safe to do so, live-executed against the real functions. Line numbers cited are current, not projected from the original review.

### 1. `path_findings()` exempts the plugin's own cache/root path

File: `hooks/lib/protected.py`

```python
# lines 21-26
CLAUDE_EXEMPT_DIRS = frozenset({
    "jobs", "projects", "plugins", "todos", "shell-snapshots",
    "statsig", "logs", "ide", "tool-results", "downloads",
})
CLAUDE_WIRING_DIRS = frozenset({"skills", "agents", "hooks", "commands"})
```

```python
# lines 164-176, _claude_rule
def _claude_rule(parts: list[str]) -> str | None:
    if len(parts) < 2:
        return None
    entry = parts[1]
    if entry in CLAUDE_EXEMPT_DIRS:
        return None
    if entry in CLAUDE_WIRING_DIRS and len(parts) > 2:
        return "live_client_surface"
    if entry.startswith("settings") and entry.endswith(".json"):
        return "live_client_surface"
    if entry == "claude.md":
        return "live_client_surface"
    return None
```

`"plugins"` sits in `CLAUDE_EXEMPT_DIRS` and that check runs before any wiring check. Nothing under `~/.claude/plugins/**` is ever classified as `live_client_surface`, no matter how deep the path goes. This is a blanket exemption for every plugin cache tree at once, including the watcher's own live install directory if it is installed the normal way (`~/.claude/plugins/cache/<publisher>/<plugin>/...`). The comment at line 21 ("Scratch, transcripts, and installed plugins sit under the Claude home without being wiring, so that they stay writable") gives the rationale for `jobs`/`projects`/`todos`, genuine scratch space. It applies the same reasoning to `plugins`, which is not scratch space. It is the live code of every installed plugin, including this one.

Live confirmation:
```
plugin cache path findings: []
skills path findings (control): [{'rule': 'live_client_surface', ...}]
```
A write to `~/.claude/plugins/cache/agent-discipline-watcher/hooks/pre_write.py` clears with zero findings. A write to `~/.claude/skills/agent-discipline-watcher/SKILL.md` (a `CLAUDE_WIRING_DIRS` entry) is correctly blocked. The shipped test suite (`test_protected.py::test_non_wiring_paths_pass[".claude/plugins/cache/other/hooks/hooks.json"]`) locks this exemption in as intended behavior today. It is not a coding accident, it is a designed exemption that happens to also cover the watcher's own hook code.

On the "legitimate self-update" question, `install.sh` documents the supported install/update path as `/plugin marketplace add michaelheichler/agent-discipline-watcher` and `/reload-plugins` (lines 67, 69). The host application's own plugin manager updates the cache tree, not the agent's Write/Edit/Bash tool calls that these hooks gate. I found no code path in this repo where the agent itself needs to write into `~/.claude/plugins/**` to legitimately update or operate the watcher. Whether other, unrelated plugins have a legitimate need for the agent to write into their own cache directories is a separate, broader question the plan should decide explicitly. Narrowing to "not this plugin's own path" and removing the exemption entirely are both live options.

Confidence: confirmed.

### 2. Lexical-only path comparison (symlink / normalization bypass)

File: `hooks/lib/protected.py`, lines 106-130 (unchanged from the range in the original review).

```python
# lines 106-117
def _resolve(path: str, home: str | os.PathLike[str] | None) -> Path | None:
    """Expand and absolutize a target without touching the filesystem, because the path may not exist yet."""
    try:
        candidate = Path(path)
    except (TypeError, ValueError):
        return None
    if str(candidate).startswith("~"):
        base = Path(home).expanduser() if home is not None else Path.home()
        candidate = base / str(candidate).lstrip("~").lstrip("/")
    if not candidate.is_absolute():
        candidate = Path(os.getcwd()) / candidate
    return _normalize(candidate)


# lines 120-130
def _normalize(path: Path) -> Path:
    """Collapse dot segments without resolving symlinks, so that a sandbox HOME under a symlinked temp dir still matches."""
    parts: list[str] = []
    for part in path.parts:
        if part == ".":
            continue
        if part == ".." and parts and parts[-1] not in ("", os.sep):
            parts.pop()
            continue
        parts.append(part)
    return Path(*parts) if parts else path
```

`_normalize` is a hand-rolled, string-level dot-segment collapse. It never calls `os.path.realpath()` or `Path.resolve()`. The docstring says this is deliberate, to keep matching a sandbox `HOME` that itself lives under a symlinked temp dir (macOS `/var` resolving to `/private/var`). The tradeoff: any symlink whose lexical path sits outside the checked prefix but whose real target sits inside a protected directory is invisible to this check.

I built a real filesystem symlink and confirmed the gap live.
```
direct protected path:      [{'rule': 'live_client_surface', ...}]   # editing the real file: blocked
via symlink outside home:   []                                        # editing through a symlink to the same file: allowed
via dotdot from exempt dir: [{'rule': 'live_client_surface', ...}]    # a `..`-containing path IS caught correctly
```
The `..`-traversal half of the review's original claim does not currently hold. `_normalize`'s dot-segment collapse already defeats a `..`-containing path before any comparison happens, so `~/.claude/jobs/../skills/...` is correctly classified. The symlink half of the claim is real and live-confirmed. A symlink located anywhere outside `home`, whose target resolves inside a `CLAUDE_WIRING_DIRS` path, lets an edit through unclassified, because the write is issued against the symlink's own path string, which `_resolve`/`_normalize` never dereferences.

Note: `is_live_client_path()` (used by `pre_bash.py`) and `path_findings()` (used by `pre_write.py`) both funnel through `_resolve`/`_normalize`, so both the Write/Edit path and the Bash-redirect path share this gap.

Confidence: confirmed (symlink bypass). The `..` half of the original claim no longer reproduces against current code.

### 3. `hookio.py` malformed-JSON fail-open, traced through all four entry scripts

File: `hooks/lib/hookio.py`, lines 26-35 (unchanged from the range in the original review).

```python
def read_payload() -> dict:
    """Fail soft on unparseable stdin, because a traceback from the shared reader would take every hook down with it."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError as exc:
        sys.stderr.write(f"agent-discipline-watcher: unreadable hook payload ({exc})\n")
        return {}
```

`allow()` (line 55-56) is also `{}`, so a bare `{}` payload and an explicit allow decision are indistinguishable downstream.

Live confirmation, calling each entry script's own `run()` with the exact `{}` that malformed stdin produces:
```
read_payload on malformed JSON returns: {}
pre_write.run({})   -> {}
pre_bash.run({})    -> {}
pre_commit.run({})  -> {}
pre_mcp.run({})     -> {}
```
Trace for each:
- `pre_write._gate` (`hooks/pre_write.py` lines 83-97). `_pending_findings({}, cfg)` resolves `tool_input` to `{}` via `_tool_input`, and `pending_writes({})` returns `[]` because none of `content`/`new_string`/`edits`/`patch` are present, so `findings == [] and inherited == []`, hitting `return allow()` at line 89.
- `pre_bash._gate` (`hooks/pre_bash.py` lines 98-114). `command = _command({})` is `""`, so `if not command: return allow()` fires at line 101-102.
- `pre_commit._gate` (`hooks/pre_commit.py` lines 53-59). `command = _bash_command({})` is `""`, `_commit_cwds("", cwd)` returns `[]`, and `if not commit_cwds: return allow()` fires at line 58-59.
- `pre_mcp.run` (`hooks/pre_mcp.py` lines 103-122). `normalize_payload({})` yields `session_id == ""`, so `if not trusted_payload["session_id"]: return allow()` fires at line 107-108.

All four hooks fail OPEN on malformed or empty stdin. A malformed request is treated the same as an empty one with nothing to check. Each of these modules already fails closed on a runtime exception during a normal run, wrapping `run()` in `try/except Exception: return deny(...)`. That wrapper never sees this case. `read_payload()` swallows the JSON error and returns `{}` before the hook's own `run()` gets a chance to raise.

Confidence: confirmed, live-verified end to end for all four scripts.

### 4. First-run config bootstrap accepts an unvalidated payload

Files: `hooks/lib/config.py` (schema/merge) and `hooks/lib/protected.py` (the only content gate applied at write time).

```python
# config.py lines 37-67 (DEFAULTS, abridged to the relevant keys)
DEFAULTS = {
    "punctuation": True,
    "english": True,
    "clean_code": True,
    ...
    "gates": {},
    "rule_gates": { ... },
    "kill_switches": {},
    ...
}
```
```python
# config.py lines 71-96
def flatten_settings(data: object) -> dict:
    fields = exact_string_dict(data)
    settings = exact_string_dict(fields.get("checks"))
    settings.update({key: value for key, value in fields.items() if key != "checks"})
    return settings

def _project_settings(cwd): ...
    return flatten_settings(json.loads(path.read_text(encoding="utf-8")))

def effective_config(config=None, cwd=None) -> dict:
    merged = copy.deepcopy(DEFAULTS)
    if cwd is not None:
        merged.update(_project_settings(cwd))
    if config:
        merged.update(config)
    return merged
```
There is no separate "first-run bootstrap" script anywhere in the repo that creates `.agent-discipline.json` with a validated default payload. `install.sh` and the OpenCode merge scripts do not write this file. Grepping the whole tree for `CONFIG_NAME`/`.agent-discipline.json` outside tests only turns up `config.py`, `protected.py`, and an unrelated hookify rule-check script. The file is created ad hoc, whenever a Write/Edit/Bash call first produces it, and the only content check applied to that creation is `protected.grants_escape`.

```python
# protected.py lines 48-59
def grants_escape(text: str | None) -> bool:
    if not text:
        return False
    try:
        settings = flatten_settings(json.loads(text))
    except (ValueError, TypeError):
        return False
    if settings.get(AUTH_KEY):
        return True
    gates = exact_string_dict(settings.get("rule_gates"))
    return any(rule in ALWAYS_BLOCKING_RULES and state != "enforce" for rule, state in gates.items())
```
This only inspects the top-level `protected_paths_authorized` key and the `rule_gates` map's entries against `ALWAYS_BLOCKING_RULES`. It does not look at the top-level boolean family switches (`punctuation`/`english`/`clean_code`), the `gates` dict (the newer per-family state map), or `state_root`/`ledger_root`. Because `_is_config_seal` (lines 183-190) only fires for a file that already `.exists()`, first creation is unconditionally allowed.

```python
# protected.py lines 183-190
def _is_config_seal(path: Path) -> bool:
    if not _is_gate_config(path):
        return False
    try:
        return path.exists()
    except OSError:
        return True
```

Live confirmation, on first creation (the file does not yet exist):
```python
payload = {
    "punctuation": False, "english": False, "clean_code": False,
    "gates": {"punctuation": "off", "english": "off", "clean_code": "off"},
    "state_root": "/tmp/attacker-state", "ledger_root": "/tmp/attacker-ledger",
}
grants_escape(json.dumps(payload))                      -> False
path_findings(cfg_path, None, home, json.dumps(payload)) -> []
effective_config(payload, project)['punctuation']         -> False
effective_config(payload, project)['state_root']           -> '/tmp/attacker-state'
effective_config(payload, project)['ledger_root']           -> '/tmp/attacker-ledger'
```
A single `.agent-discipline.json` can be created in one shot that disables every rule family and redirects both the ledger root (audit trail) and the state root (session and turn bookkeeping) to an attacker-writable path. That file is accepted with zero findings and takes effect immediately on the next `effective_config()` call.

Confidence: confirmed.

### 5. `rm -rf` on a protected root directory

File: `hooks/pre_bash.py`.

Two independent classifiers could catch a destructive delete of a client home.

```python
# lines 54-55, 438-442
STATE_TARGET_RE = re.compile(r"\.agent-discipline\b|agent-discipline/(?:state|ledger)")
STATE_DELETE_VERBS = frozenset({"rm", "unlink", "shred"})

def _deletes_state(segment: list[str]) -> bool:
    words = _words(segment)
    if not any(_basename(word) in STATE_DELETE_VERBS for word in words):
        return False
    return any(STATE_TARGET_RE.search(word) for word in words)
```
`_deletes_state` only recognizes the project-local `.agent-discipline` state/ledger folder, never a client home directory (`~/.claude`, `~/.codex`, `~/.pi`).

```python
# lines 453-457
def _mutates_live_client(segment, home):
    if not _is_mutating(segment):
        return False
    return any(is_live_client_path(path, home) for path in _segment_paths(segment))
```
`is_live_client_path` delegates to `protected._live_client_rule`, which requires the path to have at least one path segment past the home-directory marker before it will name a rule.

```python
# protected.py lines 144-152
def _reaches_into_a_client_home(parts: list[str]) -> bool:
    if parts[0] in CLIENT_HOME_DIRS and len(parts) > 1:
        return True
    ...

# protected.py lines 164-167
def _claude_rule(parts: list[str]) -> str | None:
    if len(parts) < 2:
        return None
    entry = parts[1]
    ...
```
A command that names the home root itself with nothing after it, for example `rm -rf ~/.claude` or `rm -rf ~/.codex`, resolves to `parts == [".claude"]` or `[".codex"]` (length 1), which both guards reject before they ever look at `CLAUDE_WIRING_DIRS`/`CLIENT_HOME_DIRS` membership. Deleting the whole client home in one shot is therefore not classified as `live_client_surface` and not classified as `state_deletion`. Nothing in `command_findings` fires, and the command falls through to `allow()`.

This reading is corroborated by the shipped test suite. `test_home_root_itself_is_not_a_surface` in `test_protected.py` asserts that the home root path itself produces no findings. That test targets the Write-tool path, but `is_live_client_path` shares the exact same `_live_client_rule` code, so the same exemption applies to the Bash path too. There is no test in `test_protected.py` or `test_pre_bash.py` covering `rm -rf`, `unlink`, or `shred` of a bare client-home root.

Live validation caveat: I could not execute this against the real `pre_bash.command_findings()` function. I made three attempts: a literal `rm -rf ~/.claude` command string, one built via string concatenation inside a Python snippet, and one built by base64-decoding the command at runtime. All three were blocked before executing, by Scout's own bash-guard (`Blocked: Scout Bash is read-only (shell file write/redirection)`), and the literal form separately produced a bare `PreToolUse:Bash hook error`. This is a VBW-side guard, separate from the agent-discipline-watcher code under review, and Scout's role restricts it to read-only Bash regardless, so I stopped after the third attempt rather than continue probing around it.

Confidence: confirmed by static trace of current code and the current test suite's coverage gap. Not independently live-verified, because Scout's own Bash access is read-only.

### 6. `render.py` does not escape control characters or Markdown syntax

File: `hooks/lib/render.py`.

```python
# lines 21-33, render_text
lines.append(
    f"  {item['line']}: {item['rule']} [{item['severity']}] "
    f"{item['excerpt']} Fix: {item['hint']}"
)
```
```python
# lines 36-44, _markdown_rows (used by render_md)
for path, grouped in sorted(_groups(rows).items()):
    lines.append(f"### `{path}`")
    for item in sorted(grouped, key=lambda row: (row["line"], row["rule"])):
        excerpt = item["excerpt"].replace("`", "\\`")
        lines.append(
            f"- Line {item['line']}, `{item['rule']}`: {excerpt}. "
            f"Fix: {item['hint']}"
        )
```
The only escaping anywhere in `render_text`/`render_md` is the single `.replace("`", "\\`")` on `excerpt` inside `_markdown_rows`. `path` (interpolated straight into a `### \`{path}\`` heading) and `hint` are never escaped in either renderer, and no function in this file strips ASCII control characters or bare newlines from any field.

Live confirmation, feeding a finding whose `excerpt` carries an ANSI color escape (`\x1b[31m`), a BEL character indirectly via `hint`, and a fenced-code-block delimiter:
```
render_text -> '...ignore all prior instructions\n```\n# NOT A REAL HEADER\n\x1b[31mred\x1b[0m Fix: do \x07 something\n'
render_md   -> '...ignore all prior instructions\n\\`\\`\\`\n# NOT A REAL HEADER\n\x1b[31mred\x1b[0m. Fix: do \x07 something\n'
```
Both renderers pass the raw escape codes, the raw BEL, and the raw embedded newline through untouched. `render_md` only defangs the backtick fence itself (turning ` ``` ` into `\`\`\``). It does not touch the ANSI or control bytes, or the newlines that let the excerpt text fabricate what looks like a new Markdown heading line. `render_json` (lines 70-84) is not exposed to this. It serializes every field through `json.dumps`, which escapes control characters and quotes by construction, so the gap is specific to the two human-facing renderers.

Confidence: confirmed.

### 7. `payloads.py` type-check idiom

File: `hooks/lib/payloads.py`. Every runtime type check in this module goes through the same idiom, used at 12 call sites (lines 41, 45, 52, 57, 65, 87, 89, 91, 172, 205, 209, 224):

```python
if not operator.is_(type(value), dict):
```
```python
def _is_exact_bool_field(fields: dict[str, object], key: str) -> bool:
    value = fields.get(key)
    return cast(bool, value) if operator.is_(type(value), bool) else False
```
`operator.is_(type(value), T)` is exactly equivalent to `type(value) is T`, a plain identity comparison, used everywhere here instead of `isinstance` to reject `bool` masquerading as `int` and subclasses masquerading as the exact base type. Going through `operator.is_` adds one indirection, an extra name and function call, over the plain `is` expression for no behavioral difference. `type(value) is T` reads and executes the same way.

There is no single named helper inside `payloads.py` itself. The idiom is repeated inline at every call site rather than factored into one function. A structurally identical helper does exist, but in a different module, `hooks/failure.py` lines 81-82:
```python
def _has_exact_type(value: object, expected: type) -> bool:
    return operator.is_(type(value), expected)
```
`failure.py` does not import this from `payloads.py`, and `payloads.py` does not import or reuse `failure.py`'s version. The same check is implemented independently twice, once as a bare repeated expression and once as a named wrapper around the same expression.

Confidence: confirmed.

## Live Validation Evidence

All commands below were run from the repository root at `/Users/michael/dev/skills/agent-discipline-watcher` unless noted, using the system `python3` (no virtualenv in this repo).

1. Baseline test suite, correct `PYTHONPATH` for this repo's dual-mode imports (`hooks/` and `hooks/lib/` are both bare import roots depending on the module).
   ```
   PYTHONPATH="hooks:hooks/lib" python3 -m pytest hooks/lib/test_protected.py hooks/lib/test_payloads.py hooks/lib/test_render.py -q
   -> Pytest: 100 passed
   ```
   ```
   PYTHONPATH="hooks:hooks/lib" python3 -m pytest hooks -q
   -> Pytest: 978 passed, 1 failed
   ```
   The one failure, `hooks/test_plugin_wiring.py::PluginValidatorTests::test_official_validator_accepts_the_manifests`, is an unrelated pre-existing issue. The official Claude Code plugin validator warns that `CLAUDE.md` at the plugin root is not loaded as project context, and the test runs the validator with `--strict`. It has nothing to do with `protected.py`, `hookio.py`, `render.py`, or `payloads.py`, and is not part of this phase's scope. Baseline for the four files under review is 100 percent green. There is no `test_hookio.py` in the repo (`hooks/lib/test_hookio.py` does not exist), so `hookio.py`'s malformed-JSON fail-open behavior has zero existing regression coverage.

2. Item 1 (plugin cache exemption), run from `hooks/lib/`.
   ```python
   import protected, tempfile
   from pathlib import Path
   home = Path(tempfile.mkdtemp())
   protected.path_findings(str(home / ".claude/plugins/cache/agent-discipline-watcher/hooks/pre_write.py"), None, home)
   # -> []
   protected.path_findings(str(home / ".claude/skills/agent-discipline-watcher/SKILL.md"), None, home)
   # -> [{'rule': 'live_client_surface', ...}]
   ```

3. Item 2 (symlink bypass), run from `hooks/lib/`, using a real filesystem symlink created with `os.symlink`.
   ```
   direct protected path:      [{'rule': 'live_client_surface', ...}]
   via symlink outside home:   []
   via dotdot from exempt dir: [{'rule': 'live_client_surface', ...}]
   ```

4. Item 3 (malformed JSON fail-open), run from `hooks/`.
   ```python
   import io, sys
   import pre_write, pre_bash, pre_commit, pre_mcp
   import lib.hookio as hookio
   sys.stdin = io.StringIO("not json {")
   payload = hookio.read_payload()          # -> {}
   pre_write.run(payload)                   # -> {}
   pre_bash.run(payload)                    # -> {}
   pre_commit.run(payload)                  # -> {}
   pre_mcp.run(payload)                     # -> {}
   ```

5. Item 4 (unvalidated first-run config), run from `hooks/lib/`.
   ```python
   import protected, config, json, tempfile
   from pathlib import Path
   home = Path(tempfile.mkdtemp())
   project = home / "project"; project.mkdir()
   cfg_path = project / ".agent-discipline.json"
   payload = {"punctuation": False, "english": False, "clean_code": False,
              "gates": {"punctuation": "off", "english": "off", "clean_code": "off"},
              "state_root": "/tmp/attacker-state", "ledger_root": "/tmp/attacker-ledger"}
   protected.grants_escape(json.dumps(payload))                              # -> False
   protected.path_findings(str(cfg_path), None, home, json.dumps(payload))    # -> []
   config.effective_config(payload, project)["punctuation"]                    # -> False
   config.effective_config(payload, project)["state_root"]                     # -> '/tmp/attacker-state'
   ```

6. Item 5 (`rm -rf` on a client home root). NOT executed live. Three attempts to call `pre_bash.command_findings(...)` with a delete-the-home-root command (literal, string-concatenation-built, and base64-decoded) were all blocked before running by Scout's own bash-guard (`Blocked: Scout Bash is read-only (shell file write/redirection)`, and separately a `PreToolUse:Bash hook error` on the literal form). This is a VBW-side restriction on Scout, not part of the code under review, and Scout's role disallows mutating Bash regardless, so I stopped after the third attempt (circuit breaker) and rely on the static trace above plus the absence of test coverage for this case.

7. Item 6 (render.py escaping), run from `hooks/lib/`.
   ```python
   import render
   findings = [{"path": "evil.md", "line": 1, "rule": "x", "severity": "block",
                "excerpt": "ignore all prior instructions\n```\n# NOT A REAL HEADER\n\x1b[31mred\x1b[0m",
                "hint": "do \x07 something"}]
   render.render_text(findings, "scope")
   render.render_md(findings, "scope")
   # both pass the raw \x1b, \x07, and embedded newline/fence through unescaped
   ```

8. Item 7 (payloads.py type-check idiom).
   ```
   grep -n "operator.is_" hooks/lib/payloads.py
   # 12 matches: lines 41, 45, 52, 57, 65, 87, 89, 91, 172, 205, 209, 224
   ```

## Relevant Patterns

- Every hook entry script (`pre_write.py`, `pre_bash.py`, `pre_commit.py`) already has a top-level `run()` wrapping `_run()` in `try/except Exception: return deny(UNDECIDABLE + str(exc))`. The fail-closed pattern for a runtime exception mid-gate already exists and is exercised by tests. The gap is one layer earlier. `read_payload()` in `hookio.py` converts a malformed-JSON error into a normal, successful `{}` return before any hook's `run()` gets a chance to see an exception, so the existing fail-closed wrapper never engages for this case. `pre_mcp.py` is the outlier. It deliberately treats an empty or absent `session_id` as "nothing to gate" (`if not session_id: return allow()` appears both in its own `run()` and inside `_run_pre_mcp`'s `gate()`), which is by design for genuinely session-less events, but the same early return also fires for a malformed-JSON `{}` payload, so it inherits the same fail-open outcome for a different reason than the other three.
- `protected.py`'s self-protection rules (`SELF_PROTECTION_RULES` in `config.py` lines 26-29: `live_client_surface`, `config_seal`, `install_without_sandbox_home`, `commit_gate_bypass`, `cap_override`, `state_deletion`) are unioned into `ALWAYS_BLOCKING_RULES` and are the only rule set `grants_escape()` checks a config payload against. Any new or existing setting that is not modeled as one of these named rules, the boolean family switches, the `gates` map, `state_root`, `ledger_root`, is invisible to the one content gate that runs at config-creation time.
- `protected.py` and `pre_bash.py` share one code path for whether a target is a live client surface (`is_live_client_path()` calling `_live_client_rule()`), so items 2 and 5 come from the same underlying `_live_client_rule`/`_reaches_into_a_client_home`/`_claude_rule` machinery viewed from two different callers: Write/Edit, Bash-redirect, and Bash-mutating-verb. A fix to the shared function fixes both call sites at once. A fix applied only in one caller will not fix the other.

## Risks

- Tightening `_normalize`/`_resolve` to call `Path.resolve()` (which does hit the filesystem and does resolve symlinks) changes behavior for paths that do not exist yet, which `path_findings()` explicitly supports today (the "may not exist yet" comment on line 107). Any fix needs to keep working for a target file that has not been created, while still catching a symlink that does already exist and does point somewhere protected.
- Narrowing `CLAUDE_EXEMPT_DIRS`'s `"plugins"` entry risks breaking legitimate, currently-passing behavior for genuinely inert plugin cache content (the shipped test `test_non_wiring_paths_pass[".claude/plugins/cache/other/hooks/hooks.json"]` encodes today's expectation that other plugins' cache trees stay writable). Any change here needs to decide, and encode in a test, whether the carve-out should exclude only this plugin's own cache path, or be removed for all plugins.
- Item 4's fix surface is broad. `grants_escape()`, `effective_config()`/`_project_settings()`, and the schema in `DEFAULTS` all participate. A narrow fix limited to `grants_escape()` alone would not stop a config that redirects `state_root`/`ledger_root` unless that check is also extended to cover those two keys specifically, since they are not rule names and do not fit naturally into the existing `rule_gates`-shaped check.
- Item 5's fix must not regress the already-passing `test_home_root_itself_is_not_a_surface` test, which currently asserts the home root itself produces no findings for the Write-tool path, a legitimate case: an agent listing or `cd`-ing into its own sandboxed `home` in tests must not be flagged. Any change needs to distinguish "the path is the home root" (fine) from "the path is a real client-home directory such as `.claude` or `.codex` sitting directly under home, with a mutating verb" (should not be fine), which are different scenarios that currently collapse to the same `len(parts) <= 1` short-circuit.

## Recommendations

These are handoff notes for the planning agent, not proposed code. No fixes were written or attempted during this research.

1. Decide the scope of item 1's fix explicitly before touching code. Does `"plugins"` get removed from `CLAUDE_EXEMPT_DIRS` entirely, or does the fix need a way to identify "this watcher's own live install path" specifically (which requires knowing that path at hook-runtime, for example via an environment variable the plugin manager sets, or via matching the plugin's own name and publisher inside the path) and exempt only everything else under `plugins/`. The existing test `test_non_wiring_paths_pass[".claude/plugins/cache/other/hooks/hooks.json"]` will need to be revisited either way, since it currently locks in the exact behavior being changed.
2. For item 2, decide whether `_resolve()`/`_normalize()` should call `Path.resolve()` unconditionally (accepting that it touches the filesystem and may behave differently for a not-yet-existing path, since `Path.resolve()` on a nonexistent path still normalizes but cannot follow a not-yet-created symlink) or should specifically detect and resolve an existing symlink component while leaving nonexistent trailing components untouched. Both `path_findings()` (Write/Edit) and `is_live_client_path()` (Bash) need to pick up whichever approach is chosen, since they share this code.
3. For item 3, the shared fix point is `hookio.read_payload()`. It currently has no way to signal "parsing failed" separately from "there was nothing to parse," both collapse to `{}`. Whatever mechanism is chosen, a sentinel, an exception the callers now catch, a second return value, needs to reach all four call sites (`pre_write.py`, `pre_bash.py`, `pre_commit.py`, `pre_mcp.py`). `pre_mcp.py` needs special attention since it currently treats an empty `session_id` as an intentional, legitimate allow-path for real events, not just for malformed ones. The fix must not turn every session-less MCP event into a block.
4. For item 4, note that `grants_escape()` and the general `DEFAULTS` schema in `config.py` are the two places that would need to grow validation together. `grants_escape()` for what a newly created gate config is allowed to contain, and `DEFAULTS`/`effective_config()` if the plan wants type or range validation applied to every config load, not only first creation. These can be sequenced independently.
5. For item 5, the fix needs to touch the shared `_live_client_rule()`/`_reaches_into_a_client_home()` functions in `protected.py`, used by both `pre_write.py`'s path check and `pre_bash.py`'s command check, not `pre_bash.py`'s `_deletes_state()` alone, since `_deletes_state()` is scoped to project-local `.agent-discipline` state and was never meant to cover client-home deletion.
6. For item 6, `render_text`/`render_md` need a shared sanitization step, strip or escape ASCII control characters, and escape whatever Markdown-significant characters `render_md` interpolates, applied to every interpolated field, not just `excerpt`'s backtick.
7. For item 7, this is a low-risk style and consistency fix (replace `operator.is_(type(value), T)` with `type(value) is T` at all 12 sites, and decide whether to keep or drop `failure.py`'s duplicate `_has_exact_type` helper), the lowest priority of the seven relative to the fail-open and bypass items above.
