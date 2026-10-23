"""Because a shell route can step around the discipline gates, the Bash policy blocks it before the command runs."""
from __future__ import annotations

import operator
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

from lib import imported_baseline, payloads, reporting, temp_authorship, tests_policy
from lib.baseline import committed_text
from lib.config import payload_hook_config
from lib.findings import Finding, Rule
from lib.hookio import (
    PARSE_FAILURE, advise, allow, claude_pretool_response, deny, fail_closed, read_payload, write_payload,
)
from lib.opaque_write import (
    MUTATING_VERB_RE, SHELL_C_INTERPRETERS, _bare_interpreter_name, _execution_contexts, _interpreter_run, _run_findings,
    decode_pipe_findings, dynamic_heredoc_findings, inline_interpreter_findings, inplace_edit_findings, inplace_edit_paths,
    interpreter_stdin_findings, opaque_source_findings,
)
from lib.shell_scripts import Script, awk_writes, eval_scripts, herestring_scripts
from lib.policy_cli_guard import mutates_policy
from lib.protected import POLICY_ACTION, authorized, is_install_surface_path, path_findings
from lib.reporting import compact_block, record_findings, run_with_ledger
from lib.shell_parse import (
    _bare, _basename, _command_word_index, _content_words, _is_quoted,
    _leading_assignments, _literal_contents, _logical_lines, _pipeline_groups, _redirect_paths,
    _segment_text, _segments, _words, _journal_words, command_expansions, executable_text, expansion_memo,
    heredoc_events, interpreter_invocation, line_segments, write_targets,
)
from lib.shell_expansion import Expansions
from lib.shell_lines import shell_pass
from lib.shell_routes import unplaced_content
from lib.shell_test_targets import OUTER_START, Scope, gated_paths, reachable_directories
from lib.temp_scope import (
    Directories, command_targets, joined_paths, landing_directories, outside_project_temp, scratch_target,
    segment_directories,
)
from lib.write_targets import callback_writes, generated_paths, mutation_targets, unknown_targets, writes_by_verb
from lib.write_shape import shaped_write_findings
from lib.update_policy import _segment_contexts, untrusted_update

BASH_WRITE_CAP = 100
OVERSIZE_WRITE = (
    "Shell write of {size} characters exceeds the {cap}-character cap for Bash file writes. "
    "Use the Write or Edit tool for file content."
)
INSTALLER_NAMES = frozenset({
    "install.sh", "merge-claude-settings.py", "merge-codex-config.py", "merge-codex-hooks.py",
})
CAP_VARS = frozenset({
    "CLEANCODER_FUNC_BLOCK_LINES", "ADW_FUNC_BLOCK_LINES",
    "ADW_SENTENCE_WORD_CAP", "ADW_LIST_ITEM_CAP",
    "ADW_MAX_SCAN_BYTES", "ADW_ALLOW_PROTECTED_EDIT",
})
NO_VERIFY_FLAGS = frozenset({"--no-verify", "-n"})
STATE_DELETE_VERBS = frozenset({"rm", "unlink", "shred"})
STATE_TARGET_RE = re.compile(r"\.adw\b|\.agent-discipline\b|agent-discipline/(?:state|ledger)")

WRITE_OR_EDIT_ACTION = "Use the Write or Edit tool for file content."
SAVE_THEN_RUN_ACTION = "Save the script with Write or Edit, then run the file."
MAX_SHELL_PAYLOAD_DEPTH = 1
SHELL_SCRIPTS = SHELL_C_INTERPRETERS | {"eval"}

RULES: dict[str, Rule] = {
    "install_without_sandbox_home": Rule(
        detail="Installer or updater lacks a trusted installation route",
        action=(
            "Run the updater as one plain command, with the absolute path and host flags only, "
            "for example /Users/NAME/.adw/bin/adw update --claude --codex --omp. "
            "Write no ~, $HOME, variable, pipe, redirect, or second command in it. "
            "To install from a checkout, ask the user to run ./install.sh in Terminal. "
            "Test installers only in an isolated HOME."
        ),
    ),
    "commit_gate_bypass": Rule(
        detail="Commit skips the pre-commit gate",
        action="Drop the no-verify flag and repair the reported finding.",
    ),
    "cap_override": Rule(
        detail="Discipline cap or escape overridden on the command line",
        action="Fix the code shape instead of raising the cap.",
    ),
    "state_deletion": Rule(
        detail="Watcher state or gate config deleted",
        action="Leave the state in place and repair the reported finding.",
    ),
    "state_mutation": Rule(
        detail="Watcher state or gate config mutated",
        action="Leave watcher state under host control and repair the reported finding.",
    ),
    "config_seal": Rule(
        detail="Shell command changes the project policy through adw-config",
        action=POLICY_ACTION,
    ),
    "watcher_install_surface": Rule(
        detail="Shell command mutates the live watcher install",
        action="Change the repo source and reinstall instead of editing the live install.",
    ),
    "inline_interpreter_write": Rule(
        detail="Inline interpreter payload can write or is unreadable",
        action=WRITE_OR_EDIT_ACTION,
    ),
    "shell_payload_block": Rule(
        detail="Shell -c payload is unreadable or nested past one level",
        action=WRITE_OR_EDIT_ACTION,
    ),
    "interpreter_heredoc_write": Rule(
        detail="Heredoc or pipe feeding an interpreter's stdin can write or is unreadable",
        action=SAVE_THEN_RUN_ACTION,
    ),
    "dynamic_heredoc_write": Rule(
        detail="Dynamic or unterminated heredoc aimed at a file",
        action=WRITE_OR_EDIT_ACTION,
    ),
    "decode_pipe_write": Rule(
        detail="Decode pipe ends in a file write",
        action=WRITE_OR_EDIT_ACTION,
    ),
    "inplace_edit_write": Rule(
        detail="In-place editor mutates a file outside the Edit tool",
        action=WRITE_OR_EDIT_ACTION,
    ),
    "opaque_source_write": Rule(
        detail="Opaque copy source feeds a file write",
        action=WRITE_OR_EDIT_ACTION,
    ),
    "dynamic_write_target": Rule(
        detail="Shell write destination is unknown before the command runs",
        action="Use an absolute literal destination, or the Write or Edit tool for file content.",
    ),
}


def run(payload: dict, config: dict | None = None) -> dict:
    """Fail closed because an undecidable command cannot be proven safe to execute."""
    return fail_closed("command", lambda: _checked_run(payload, config))


def _checked_run(payload: dict, config: dict | None) -> dict:
    if payload is PARSE_FAILURE:
        raise ValueError("unreadable hook payload")
    with expansion_memo():
        return _run(payload, config)


def _run(payload: dict, config: dict | None) -> dict:
    cfg = payload_hook_config(config, payload)
    return run_with_ledger(
        hook="pre_bash",
        payload=payload,
        gate=lambda turn_id: _gate(payload, cfg, turn_id),
        ledger_root=cfg.get("ledger_root"),
        state_root=cfg.get("state_root"),
    )


def _gate(payload: dict, cfg: dict, turn_id: str) -> dict:
    started = time.monotonic()
    command = _command(payload)
    if not command:
        return allow()
    cwd = payload.get("cwd") or "."
    refusal = temp_authorship.scratch_refusal(payloads.session_id(payload), write_paths(command, cwd), cwd, cfg.get("state_root"))
    if refusal:
        return deny(refusal)
    _note_first_seen(payload, cwd, cfg)
    findings = command_findings(command, cfg, cwd=cwd) + target_findings(command, cfg, cwd=cwd) + opaque_write_findings(command, cfg, cwd=cwd)
    findings += dynamic_target_findings(command, cfg, cwd) + _test_findings(payload, cfg)
    if findings:
        reason, _ = compact_block(findings, cfg)
        _record(payload, cfg, turn_id, findings, started)
        return deny(reason)
    scan_targets = _scan_targets(command)
    size = _largest_oversize(scan_targets, cwd)
    if size is not None:
        return deny(OVERSIZE_WRITE.format(size=size, cap=BASH_WRITE_CAP))
    owned, inherited = _write_shape_totals(scan_targets, cfg, Path(cwd))
    if not owned and not inherited:
        return allow()
    decisions = _record(payload, cfg, turn_id, owned, started) if owned else []
    return _verdict(decisions, cfg, inherited)


def _note_first_seen(payload: dict, cwd: str, cfg: dict) -> None:
    """Taken before the command runs, because an untracked file has no other record of the text the agent found."""
    paths = [payloads.resolved_path(raw, Path(cwd)) for raw in payloads.edited_paths(payload)]
    imported_baseline.note_first_seen(
        payloads.session_id(payload), [str(path) for path in paths if not outside_project_temp(path, cwd)],
        cfg.get("state_root"), lambda path: committed_text(path) is not None,
    )


def _test_findings(payload: dict, cfg: dict) -> list[dict]:
    """Every scan target, because sh -c can wrap the write."""
    gate = tests_policy.Gate(payload, cfg, time.time())
    if tests_policy.gate_open(gate):
        return []
    cwd = Path(payload.get("cwd") or ".")
    command = _command(payload)
    payload_start = reachable_directories(command, cwd)
    texts: dict[str, str | None] = {}
    unresolved: list[str] = []
    for position, target in enumerate(_scan_targets(command)):
        texts.update(_shell_targets(target, cwd))
        scope = Scope(cwd, OUTER_START if position == 0 else payload_start, outer=position == 0)
        paths, unnamed = gated_paths(target, scope)
        texts.update({path: texts.get(path) for path in paths})
        unresolved.extend(unnamed)
    changes = [
        tests_policy.PendingChange(path, tests_policy.read_before(payloads.resolved_path(path, cwd)), text)
        for path, text in texts.items()
    ]
    return tests_policy.findings(gate, changes, unresolved)


def _scan_targets(command: str) -> list[str]:
    expansions = command_expansions(command)
    scripts = [*herestring_scripts(command, expansions), *eval_scripts(command, expansions)]
    bodies = [script.body for script in scripts if script.body and script.interpreter in SHELL_SCRIPTS]
    return (
        [command] + _literal_shell_c_payloads(command)
        + _literal_shell_stdin_payloads(command) + _literal_shell_pipe_payloads(command)
        + _substitution_bodies(command) + bodies
    )


def _write_shape_totals(scan_targets: list[str], cfg: dict, cwd: Path) -> tuple[list[dict], list[dict]]:
    """Pool owned and inherited findings across every scan target, because a shell -c payload adds its own writes to the outer command's."""
    owned: list[dict] = []
    inherited: list[dict] = []
    for target in scan_targets:
        target_owned, target_inherited = shaped_write_findings(target, cfg, cwd)
        owned.extend(target_owned)
        inherited.extend(target_inherited)
    return owned, inherited


def _record(payload: dict, cfg: dict, turn_id: str, findings: list[dict], started: float) -> list[tuple[dict, str]]:
    return record_findings(
        session_id=str(payload.get("session_id") or ""), hook="pre_bash",
        event="PreToolUse", findings=findings, turn_id=turn_id,
        tool_use_id=str(payload.get("tool_use_id") or ""),
        duration_ms=int((time.monotonic() - started) * 1000),
        root=cfg.get("ledger_root"), config=cfg,
    )


def _verdict(decisions: list[tuple[dict, str]], cfg: dict, inherited: list[dict] | None = None) -> dict:
    kind, reason = reporting.verdict_message(decisions, cfg)
    if kind == "block":
        return deny(reason)
    notice = reporting.inherited_advice(inherited or [], cfg)
    if kind == "observe":
        return advise("\n".join(part for part in (reason, notice) if part), "PreToolUse")
    return advise(notice, "PreToolUse") if notice else allow()


def command_findings(command: str, config: dict | None = None, home: str | os.PathLike[str] | None = None, cwd: str | os.PathLike[str] | None = None) -> list[dict]:
    """Judge shell segments independently because an allowed segment must not hide a prohibited sibling."""
    if not command or authorized(config):
        return []
    segments = _command_segments(command)
    contexts = _segment_cwds(command, cwd, home)
    hits = []
    if any(
        (_runs_installer(segment) and not _sets_home(segment)) or untrusted_update(segment, home, segment_cwd)
        for segment, segment_cwd in contexts
    ):
        hits.append("install_without_sandbox_home")
    if any(_skips_commit_gate(segment) for segment in segments):
        hits.append("commit_gate_bypass")
    if any(_overrides_cap(segment) for segment in segments):
        hits.append("cap_override")
    hits += _protected_target_hits(segments, command_expansions(command, cwd), home)
    if any(mutates_policy(segment, segment_cwd) for segment, segment_cwd in contexts):
        hits.append("config_seal")
    return [_finding(rule, command) for rule in hits]


def _protected_target_hits(segments: list[list[str]], expansions: Expansions, home: str | os.PathLike[str] | None) -> list[str]:
    hits = []
    if any(_deletes_state(segment, expansions) for segment in segments):
        hits.append("state_deletion")
    elif any(_mutates_state(segment, expansions) for segment in segments):
        hits.append("state_mutation")
    if any(_mutates_install_surface(segment, home, expansions) for segment in segments):
        hits.append("watcher_install_surface")
    return hits


def _segment_views(command: str) -> list[list[list[str]]]:
    """Both views, because the joined one keeps executed heredoc bodies and the line one keeps every later command."""
    return [_segments(executable_text(command)), line_segments(command)]


def _command_segments(command: str) -> list[list[str]]:
    unique = {tuple(segment): segment for view in _segment_views(command) for segment in view}
    return list(unique.values())


def _segment_cwds(command: str, cwd: str | os.PathLike[str] | None, home: str | os.PathLike[str] | None) -> list[tuple[list[str], Path]]:
    """Because each view tracks its own cd, contexts come per view, and a pair both views share counts once."""
    unique = {}
    for view in _segment_views(command):
        for segment, segment_cwd in _segment_contexts(view, cwd, home):
            unique.setdefault((tuple(segment), segment_cwd), (segment, segment_cwd))
    return list(unique.values())


def target_findings(command: str, config: dict | None = None, home: str | os.PathLike[str] | None = None, cwd: str | os.PathLike[str] | None = None) -> list[dict]:
    """Apply the protected-path policy to shell writes, because a redirect reaches the same files the Write tool does."""
    findings = []
    for path, text in _shell_targets(command, cwd).items():
        for finding in path_findings(_session_path(path, cwd), config, home, text):
            item = dict(finding)
            item["path"] = path
            findings.append(item)
    return findings


def _session_path(path: str, cwd: str | os.PathLike[str] | None) -> str:
    """Join cwd, because the hook process runs somewhere else."""
    if cwd is None or path.startswith("~") or os.path.isabs(path):
        return path
    return os.path.join(cwd, path)


def _shell_targets(command: str, cwd: str | os.PathLike[str] | None = None) -> dict[str, str | None]:
    """Retain targets with unknown content because protected-path checks still apply when content inspection cannot."""
    targets: dict[str, str | None] = {path: None for path in _mutation_paths(command, cwd)}
    targets.update({path: None for path in write_paths(command, cwd)})
    targets.update(dict(write_targets(command)))
    return targets


def opaque_write_findings(command: str, config: dict | None = None, cwd: str | os.PathLike[str] | None = None) -> list[dict]:
    """Hard block here, because a write route the scanner cannot read through cannot be judged any other way."""
    return _opaque_findings(command, config, 0, cwd)


def _opaque_findings(
    command: str,
    config: dict | None,
    depth: int,
    cwd: str | os.PathLike[str] | None = None,
) -> list[dict]:
    if not command or authorized(config):
        return []
    make_finding = _finding_factory(command)
    findings: list[dict] = []
    findings.extend(inline_interpreter_findings(command, make_finding, cwd=cwd))
    findings.extend(interpreter_stdin_findings(command, make_finding, _stdin_recurse(command, config, depth, cwd), cwd=cwd))
    findings.extend(dynamic_heredoc_findings(command, make_finding))
    findings.extend(decode_pipe_findings(command, make_finding))
    findings.extend(inplace_edit_findings(command, make_finding, cwd=cwd))
    findings.extend(opaque_source_findings(command, make_finding))
    findings.extend([make_finding("opaque_source_write")] if unplaced_content(command) else [])
    findings.extend(_shell_payload_findings(command, config, depth, cwd))
    findings.extend(_script_findings(command, config, depth, cwd))
    return findings


def _script_findings(command: str, config: dict | None, depth: int, cwd: str | os.PathLike[str] | None) -> list[dict]:
    """Because a quoted $(...) runs in this shell while eval and a here-string re-read a script, only those two meet the nesting cap."""
    findings = [row for body in shell_pass(command).substitutions for row in _recursed_findings(body, config, depth, cwd)]
    expansions = command_expansions(command, cwd)
    contexts = _execution_contexts(command, cwd)
    nested = None if depth >= MAX_SHELL_PAYLOAD_DEPTH else lambda body: _recursed_findings(body, config, depth + 1, cwd)
    for script in [*herestring_scripts(command, expansions), *eval_scripts(command, expansions)]:
        findings += _script_rows(script, command, contexts, nested)
    return findings + ([_finding("inline_interpreter_write", command)] if awk_writes(command, expansions) else [])


def _script_rows(script: Script, command: str, contexts: dict, nested: Callable[[str], list[dict]] | None) -> list[dict]:
    if script.interpreter not in SHELL_SCRIPTS:
        run = _interpreter_run(script.interpreter, script.body, script.segment, contexts)
        return _run_findings(run, _finding_factory(command), "interpreter_heredoc_write")
    if script.body is None or nested is None:
        return [_finding("shell_payload_block", command)]
    return nested(script.body)


def _stdin_recurse(
    command: str,
    config: dict | None,
    depth: int,
    cwd: str | os.PathLike[str] | None,
) -> Callable[[str], list[dict]]:
    """Close over the outer command and its recursion depth, because a shell consumer's literal stdin body is a fresh command one level deeper, capped the same as a shell -c payload."""
    def recurse(body: str) -> list[dict]:
        if depth >= MAX_SHELL_PAYLOAD_DEPTH:
            return [_finding("interpreter_heredoc_write", command)]
        return _recursed_findings(body, config, depth + 1, cwd)
    return recurse


def _finding_factory(command: str) -> Callable[[str], dict]:
    """Close over the command once here, because every opaque-write detector needs it only to build the finding's snippet."""
    def make_finding(rule: str) -> dict:
        return _finding(rule, command)
    return make_finding


def _shell_payload_findings(
    command: str,
    config: dict | None,
    depth: int,
    cwd: str | os.PathLike[str] | None,
) -> list[dict]:
    findings = []
    for segment, segment_cwd in _segment_cwds(command, cwd, None):
        invocation = interpreter_invocation(segment)
        if invocation is None or invocation.interpreter not in SHELL_C_INTERPRETERS:
            continue
        if invocation.payload is None or depth >= MAX_SHELL_PAYLOAD_DEPTH:
            findings.append(_finding("shell_payload_block", command))
            continue
        findings.extend(_recursed_findings(invocation.payload, config, depth + 1, segment_cwd))
    return findings


def _recursed_findings(
    payload: str,
    config: dict | None,
    depth: int,
    cwd: str | os.PathLike[str] | None,
) -> list[dict]:
    """Re-enter one level of the gate's own self-protection checks, because a literal shell -c payload is a fresh command."""
    return (
        command_findings(payload, config, cwd=cwd)
        + target_findings(payload, config, cwd=cwd)
        + _opaque_findings(payload, config, depth, cwd)
        + dynamic_target_findings(payload, config, cwd)
    )


def dynamic_target_findings(command: str, config: dict | None = None, cwd: str | os.PathLike[str] | None = None) -> list[dict]:
    """One row per destination, because a path known only at run time can be any protected file."""
    if not command or authorized(config):
        return []
    rule = RULES["dynamic_write_target"]
    return [
        {**_finding("dynamic_write_target", command), "detail": f"{rule.detail}: {word}", "match": word}
        for word in unresolved_write_destinations(command, OUTER_START, cwd)
    ]


def unresolved_write_destinations(command: str, start: Directories = OUTER_START, cwd: str | os.PathLike[str] | None = None) -> list[str]:
    """Public, because write_paths drops these words and a caller that must fail closed still has to see them."""
    expansions = command_expansions(command, cwd)
    segments = line_segments(command)
    words: list[str] = []
    for segment, folders in zip(segments, segment_directories(segments, start, expansions.path)):
        words += unknown_targets(segment, expansions) if _is_mutating(segment) else []
        words += callback_writes(segment, expansions)
        words += [] if folders is not None else _lost_destinations(segment, expansions, cwd)
    return list(dict.fromkeys(map(_bare, words)))


def _lost_destinations(segment: list[str], expansions: Expansions, cwd: str | os.PathLike[str] | None) -> list[str]:
    """Relative writes after an unknown cd, its sh -c payload and $(...) bodies included, because they land where no one can say."""
    lost = [path for path in mutation_targets(segment, expansions) if not path.startswith("~") and not os.path.isabs(path)]
    invocation = interpreter_invocation(segment)
    scripts = shell_pass(" ".join(segment)).substitutions
    scripts += [invocation.payload] if invocation and invocation.interpreter in SHELL_C_INTERPRETERS and invocation.payload else []
    return lost + [word for script in scripts for word in unresolved_write_destinations(script, None, cwd)]


def _literal_shell_c_payloads(command: str) -> list[str]:
    """List one level of literal shell -c payloads, because the oversize cap and content scanner must see through the same wrapper the self-protection checks already re-enter."""
    payloads = []
    for segment in _command_segments(command):
        invocation = interpreter_invocation(segment)
        if invocation is not None and invocation.interpreter in SHELL_C_INTERPRETERS and invocation.payload is not None:
            payloads.append(invocation.payload)
    return list(dict.fromkeys(payloads))


def _substitution_bodies(command: str) -> list[str]:
    """Because bash runs a quoted $(...) before the command holding it, each nested body is judged, and each is shorter so the walk ends."""
    found: list[str] = []
    queue = shell_pass(command).substitutions
    while queue:
        body = queue.pop(0)
        found.append(body)
        queue.extend(shell_pass(body).substitutions)
    return found


def _literal_shell_stdin_payloads(command: str) -> list[str]:
    """List one level of literal heredoc bodies feeding a bare shell interpreter's stdin, because the oversize cap and content scanner must see through that wrapper the same way they already see through a literal shell -c payload."""
    return [
        event.body for event in heredoc_events(command)
        if not event.dynamic and _bare_interpreter_name(event.consumer_segment) in SHELL_C_INTERPRETERS
    ]


def _pipe_stdin_payload(group: list[list[str]]) -> str | None:
    """Return the joined producer text only when every producer segment and the pipe's shape are fully literal, because a guessed body would misreport what the consumer actually receives."""
    if len(group) < 2 or _bare_interpreter_name(group[-1]) not in SHELL_C_INTERPRETERS:
        return None
    producer_texts = _literal_contents(group[:-1])
    if len(producer_texts) != len(group) - 1 or None in producer_texts:
        return None
    return "\n".join(producer_texts)


def _literal_shell_pipe_payloads(command: str) -> list[str]:
    """List one level of literal pipe producer text feeding a bare shell interpreter's stdin, because the oversize cap and content scanner must see through that wrapper the same way they already see through a literal shell -c payload."""
    groups = [group for line, _, _ in _logical_lines(command) for group in _pipeline_groups(line)]
    payloads = [_pipe_stdin_payload(group) for group in groups]
    return [payload for payload in payloads if payload is not None]


def _largest_oversize(commands: list[str], cwd: str | os.PathLike[str] | None = None) -> int | None:
    """Check every scan target here, because a write wrapped in a literal shell -c payload must face the same cap as a bare one."""
    sizes = [oversize_write(command, cwd) for command in commands]
    known = [size for size in sizes if size is not None]
    return max(known) if known else None


def oversize_write(command: str, cwd: str | os.PathLike[str] | None = None) -> int | None:
    """Because scratch temp text is no project output, a write whose every target is scratch temp faces no cap."""
    sizes = [len(text) for path, text in write_targets(command) if not scratch_target(path, command, cwd)]
    expansions = command_expansions(command, cwd)
    for line, _, raw_bodies in _logical_lines(command):
        paths = [expansions.path(word) for segment in _segments(line) for word, _ in _content_words(segment)]
        if paths and not all(path is not None and scratch_target(path, command, cwd) for path in paths):
            sizes.extend(len(body) for body in raw_bodies)
    oversized = [size for size in sizes if size > BASH_WRITE_CAP]
    return max(oversized) if oversized else None


def write_paths(command: str, cwd: str | os.PathLike[str] | None = None) -> list[str]:
    """Because PostToolUse journals these paths as the agent's writes, in-place edit files count and a cd moves the relative ones."""
    expansions = command_expansions(command, cwd)
    segments = line_segments(command)
    redirected = [
        path for segment, folders in zip(segments, landing_directories(segments, cwd, expansions.path))
        for path in joined_paths(_destinations(segment, expansions), folders)
    ]
    return redirected + [target for path in inplace_edit_paths(command) for target in command_targets(path, command, cwd)]


def _destinations(segment: list[str], expansions: Expansions) -> list[str]:
    redirected = [path for path in (expansions.path(word) for word, _ in _journal_words(segment)) if path is not None]
    return redirected + generated_paths(segment, expansions)


def _mutation_paths(command: str, cwd: str | os.PathLike[str] | None = None) -> list[str]:
    """Resolved per segment through the verb-aware destination rules, because a redirect elsewhere in the segment must not turn a read argument into a write target."""
    expansions = command_expansions(command, cwd)
    return [path for segment in _command_segments(command) if _is_mutating(segment) for path in mutation_targets(segment, expansions)]


def write_findings(command: str, config: dict | None = None, cwd: str | os.PathLike[str] | None = None) -> list[dict]:
    """Scan literal shell writes, because PostToolUse never matches Bash and this content would otherwise land unread."""
    return shaped_write_findings(command, config, cwd)[0]


def _sets_home(segment: list[str]) -> bool:
    return "HOME" in _leading_assignments(segment)



def _overrides_cap(segment: list[str]) -> bool:
    return any(name in CAP_VARS for name in _leading_assignments(segment))



def _runs_installer(segment: list[str]) -> bool:
    """Because a quoted mention or an env-var prefix must never hide a real invocation, resolve the actual command word first."""
    index = _command_word_index(segment)
    return index < len(segment) and _basename(segment[index]) in INSTALLER_NAMES



def _skips_commit_gate(segment: list[str]) -> bool:
    words = _words(segment)
    if "git" not in words or "commit" not in words:
        return False
    if words.index("git") > words.index("commit"):
        return False
    return any(token in NO_VERIFY_FLAGS for token in segment if not _is_quoted(token))



def _deletes_state(segment: list[str], expansions: Expansions) -> bool:
    if not any(_basename(word) in STATE_DELETE_VERBS for word in _words(segment)):
        return False
    return _targets_state(segment, expansions)


def _mutates_state(segment: list[str], expansions: Expansions) -> bool:
    return _is_mutating(segment) and _targets_state(segment, expansions)


def _targets_state(segment: list[str], expansions: Expansions) -> bool:
    """Judged against the resolved destinations rather than every word, because naming the state root as a read argument is not a mutation of it."""
    return any(STATE_TARGET_RE.search(target) for target in mutation_targets(segment, expansions))



def _is_mutating(segment: list[str]) -> bool:
    """Report the mutating shell forms, so that a read of a protected path stays allowed."""
    return bool(_redirect_paths(segment)) or bool(MUTATING_VERB_RE.search(_segment_text(segment))) or writes_by_verb(segment)



def _mutates_install_surface(segment: list[str], home: str | os.PathLike[str] | None, expansions: Expansions) -> bool:
    """Require the mutating form and the install target inside the same segment, so that a read stays allowed."""
    if not _is_mutating(segment):
        return False
    return any(is_install_surface_path(path, home) for path in mutation_targets(segment, expansions))


def _finding(rule: str, command: str) -> dict:
    rule_spec = RULES[rule]
    return Finding(
        family="self_protection",
        rule=rule,
        line=1,
        detail=rule_spec.detail,
        force=True,
        snippet=command.strip()[:180],
        action=rule_spec.action,
        path=None,
        severity=None,
        tool_use_id=None,
    ).to_dict()



def _command(payload: dict) -> str:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    command = tool_input.get("command") if operator.is_(type(tool_input), dict) else None
    if not operator.is_(type(command), str):
        raise ValueError("Bash tool_input.command must be a string")
    return command


if __name__ == "__main__":
    write_payload(claude_pretool_response(run(read_payload())))
