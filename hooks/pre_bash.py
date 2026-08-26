"""Bash command policy: block shell routes around the discipline gates before the command runs."""
from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from pathlib import Path

from lib import reporting
from lib.config import effective_hook_config
from lib.findings import Finding, Rule
from lib.hookio import (
    PARSE_FAILURE, advise, allow, claude_pretool_response, deny, fail_closed, read_payload, write_payload,
)
from lib.opaque_write import (
    MUTATING_VERB_RE, SHELL_C_INTERPRETERS, _bare_interpreter_name, decode_pipe_findings, dynamic_heredoc_findings,
    inline_interpreter_findings, inplace_edit_findings, interpreter_stdin_findings, opaque_source_findings,
)
from lib.protected import authorized, is_install_surface_path, path_findings
from lib.reporting import compact_block, record_findings, run_with_ledger
from lib.shell_parse import (
    _basename, _command_word_index, _is_quoted,
    _leading_assignments, _literal_contents, _logical_lines, _pipeline_groups, _redirect_paths,
    _segment_text, _segments, _words, _write_paths, heredoc_events, interpreter_invocation, write_paths, write_targets,
)
from lib.write_targets import mutation_targets
from lib.write_shape import shaped_write_findings

BASH_WRITE_CAP = 100
OVERSIZE_WRITE = (
    "Shell write of {size} characters exceeds the {cap}-character cap for Bash file writes. "
    "Use the Write or Edit tool for file content."
)
INSTALLER_NAMES = frozenset({
    "install.sh", "merge-claude-settings.py", "merge-codex-config.py",
})
CAP_VARS = frozenset({
    "CLEANCODER_FUNC_BLOCK_LINES", "CLEANCODER_FILE_BLOCK_LINES",
    "ADW_FUNC_BLOCK_LINES", "ADW_FILE_BLOCK_LINES",
    "ADW_SENTENCE_WORD_CAP", "ADW_LIST_ITEM_CAP",
    "ADW_MAX_SCAN_BYTES", "ADW_ALLOW_PROTECTED_EDIT",
})
NO_VERIFY_FLAGS = frozenset({"--no-verify", "-n"})
STATE_DELETE_VERBS = frozenset({"rm", "unlink", "shred"})
STATE_TARGET_RE = re.compile(r"\.agent-discipline\b|agent-discipline/(?:state|ledger)")

WRITE_OR_EDIT_ACTION = "Use the Write or Edit tool for file content."
MAX_SHELL_PAYLOAD_DEPTH = 1

RULES: dict[str, Rule] = {
    "install_without_sandbox_home": Rule(
        detail="Installer or merge script aimed at the real HOME",
        action="Re-run it with a sandbox HOME such as HOME=\"$(mktemp -d)\".",
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
        action=WRITE_OR_EDIT_ACTION,
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
}


def run(payload: dict, config: dict | None = None) -> dict:
    """Fail closed because an undecidable command cannot be proven safe to execute."""
    return fail_closed("command", lambda: _checked_run(payload, config))


def _checked_run(payload: dict, config: dict | None) -> dict:
    if payload is PARSE_FAILURE:
        raise ValueError("unreadable hook payload")
    return _run(payload, config)


def _run(payload: dict, config: dict | None) -> dict:
    cfg = effective_hook_config(config, payload.get("cwd") or None)
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
    findings = command_findings(command, cfg) + target_findings(command, cfg) + opaque_write_findings(command, cfg)
    if findings:
        reason, _ = compact_block(findings, cfg)
        _record(payload, cfg, turn_id, findings, started)
        return deny(reason)
    scan_targets = (
        [command] + _literal_shell_c_payloads(command)
        + _literal_shell_stdin_payloads(command) + _literal_shell_pipe_payloads(command)
    )
    size = _largest_oversize(scan_targets)
    if size is not None:
        return deny(OVERSIZE_WRITE.format(size=size, cap=BASH_WRITE_CAP))
    owned, inherited = _write_shape_totals(scan_targets, cfg, Path(payload.get("cwd") or "."))
    if not owned and not inherited:
        return allow()
    decisions = _record(payload, cfg, turn_id, owned, started) if owned else []
    return _verdict(decisions, cfg, inherited)


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
    return {"systemMessage": notice} if notice else allow()


def command_findings(command: str, config: dict | None = None, home: str | os.PathLike[str] | None = None) -> list[dict]:
    """Judge shell segments independently because an allowed segment must not hide a prohibited sibling."""
    if not command or authorized(config):
        return []
    segments = _segments(command)
    hits = []
    if any(_runs_installer(segment) and not _sets_home(segment) for segment in segments):
        hits.append("install_without_sandbox_home")
    if any(_skips_commit_gate(segment) for segment in segments):
        hits.append("commit_gate_bypass")
    if any(_overrides_cap(segment) for segment in segments):
        hits.append("cap_override")
    if any(_deletes_state(segment) for segment in segments):
        hits.append("state_deletion")
    if "state_deletion" not in hits and any(_mutates_state(segment) for segment in segments):
        hits.append("state_mutation")
    if any(_mutates_install_surface(segment, home) for segment in segments):
        hits.append("watcher_install_surface")
    return [_finding(rule, command) for rule in hits]


def target_findings(command: str, config: dict | None = None, home: str | os.PathLike[str] | None = None) -> list[dict]:
    """Apply the protected-path policy to shell writes, because a redirect reaches the same files the Write tool does."""
    findings = []
    for path, text in _shell_targets(command).items():
        for finding in path_findings(path, config, home, text):
            item = dict(finding)
            item["path"] = path
            findings.append(item)
    return findings


def _shell_targets(command: str) -> dict[str, str | None]:
    """Retain targets with unknown content because protected-path checks still apply when content inspection cannot."""
    targets: dict[str, str | None] = {path: None for path in _mutation_paths(command)}
    targets.update({path: None for path in write_paths(command)})
    targets.update(dict(write_targets(command)))
    return targets


def opaque_write_findings(command: str, config: dict | None = None) -> list[dict]:
    """Hard block here, because a write route the scanner cannot read through cannot be judged any other way."""
    return _opaque_findings(command, config, 0)


def _opaque_findings(command: str, config: dict | None, depth: int) -> list[dict]:
    if not command or authorized(config):
        return []
    make_finding = _finding_factory(command)
    findings: list[dict] = []
    findings.extend(inline_interpreter_findings(command, make_finding))
    findings.extend(interpreter_stdin_findings(command, make_finding, _stdin_recurse(command, config, depth)))
    findings.extend(dynamic_heredoc_findings(command, make_finding))
    findings.extend(decode_pipe_findings(command, make_finding))
    findings.extend(inplace_edit_findings(command, make_finding))
    findings.extend(opaque_source_findings(command, make_finding))
    findings.extend(_shell_payload_findings(command, config, depth))
    return findings


def _stdin_recurse(command: str, config: dict | None, depth: int) -> Callable[[str], list[dict]]:
    """Close over the outer command and its recursion depth, because a shell consumer's literal stdin body is a fresh command one level deeper, capped the same as a shell -c payload."""
    def recurse(body: str) -> list[dict]:
        if depth >= MAX_SHELL_PAYLOAD_DEPTH:
            return [_finding("interpreter_heredoc_write", command)]
        return _recursed_findings(body, config, depth + 1)
    return recurse


def _finding_factory(command: str) -> Callable[[str], dict]:
    """Close over the command once here, because every opaque-write detector needs it only to build the finding's snippet."""
    def make_finding(rule: str) -> dict:
        return _finding(rule, command)
    return make_finding


def _shell_payload_findings(command: str, config: dict | None, depth: int) -> list[dict]:
    findings = []
    for segment in _segments(command):
        invocation = interpreter_invocation(segment)
        if invocation is None or invocation.interpreter not in SHELL_C_INTERPRETERS:
            continue
        if invocation.payload is None or depth >= MAX_SHELL_PAYLOAD_DEPTH:
            findings.append(_finding("shell_payload_block", command))
            continue
        findings.extend(_recursed_findings(invocation.payload, config, depth + 1))
    return findings


def _recursed_findings(payload: str, config: dict | None, depth: int) -> list[dict]:
    """Re-enter one level of the gate's own self-protection checks, because a literal shell -c payload is a fresh command."""
    return command_findings(payload, config) + target_findings(payload, config) + _opaque_findings(payload, config, depth)


def _literal_shell_c_payloads(command: str) -> list[str]:
    """List one level of literal shell -c payloads, because the oversize cap and content scanner must see through the same wrapper the self-protection checks already re-enter."""
    payloads = []
    for segment in _segments(command):
        invocation = interpreter_invocation(segment)
        if invocation is not None and invocation.interpreter in SHELL_C_INTERPRETERS and invocation.payload is not None:
            payloads.append(invocation.payload)
    return payloads


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


def _largest_oversize(commands: list[str]) -> int | None:
    """Check every scan target here, because a write wrapped in a literal shell -c payload must face the same cap as a bare one."""
    sizes = [oversize_write(command) for command in commands]
    known = [size for size in sizes if size is not None]
    return max(known) if known else None


def oversize_write(command: str) -> int | None:
    sizes = [len(text) for _, text in write_targets(command)]
    for line, _, raw_bodies in _logical_lines(command):
        if not any(_write_paths(segment) for segment in _segments(line)):
            continue
        sizes.extend(len(body) for body in raw_bodies)
    oversized = [size for size in sizes if size > BASH_WRITE_CAP]
    return max(oversized) if oversized else None


def _mutation_paths(command: str) -> list[str]:
    """Resolved per segment through the verb-aware destination rules, because a redirect elsewhere in the segment must not turn a read argument into a write target."""
    return [path for segment in _segments(command) if _is_mutating(segment) for path in mutation_targets(segment)]


def write_findings(
    command: str, config: dict | None = None, cwd: str | os.PathLike[str] | None = None,
) -> list[dict]:
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



def _deletes_state(segment: list[str]) -> bool:
    if not any(_basename(word) in STATE_DELETE_VERBS for word in _words(segment)):
        return False
    return _targets_state(segment)


def _mutates_state(segment: list[str]) -> bool:
    return _is_mutating(segment) and _targets_state(segment)


def _targets_state(segment: list[str]) -> bool:
    """Judged against the resolved destinations rather than every word, because naming the state root as a read argument is not a mutation of it."""
    return any(STATE_TARGET_RE.search(target) for target in mutation_targets(segment))



def _is_mutating(segment: list[str]) -> bool:
    """Report the mutating shell forms, so that a read of a protected path stays allowed."""
    return bool(_redirect_paths(segment)) or bool(MUTATING_VERB_RE.search(_segment_text(segment)))



def _mutates_install_surface(segment: list[str], home: str | os.PathLike[str] | None) -> bool:
    """Require the mutating form and the install target inside the same segment, so that a read stays allowed."""
    if not _is_mutating(segment):
        return False
    return any(is_install_surface_path(path, home) for path in mutation_targets(segment))


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
    command = tool_input.get("command") or tool_input.get("cmd") or ""
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return str(command)


if __name__ == "__main__":
    write_payload(claude_pretool_response(run(read_payload())))
