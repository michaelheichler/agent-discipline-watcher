"""Bash command policy: block shell routes around the discipline gates before the command runs."""
from __future__ import annotations

import os
import re
import time

from lib import reporting
from lib.config import effective_hook_config
from lib.hookio import (
    PARSE_FAILURE, advise, allow, claude_pretool_response, deny, fail_closed, read_payload, write_payload,
)
from lib.protected import authorized, is_live_client_path, path_findings
from lib.reporting import compact_block, record_findings, run_with_ledger
from lib.scanner import scan_all, scannable_text
from lib.shell_parse import (
    _bare, _basename, _command_word_index, _expand_home, _is_file_target, _is_quoted,
    _leading_assignments, _logical_lines, _redirect_paths, _segment_paths, _segment_text, _segments, _words,
    _write_paths, write_paths, write_targets,
)

BASH_WRITE_CAP = 100
OVERSIZE_WRITE = (
    "Shell write of {size} characters exceeds the {cap}-character cap for Bash file writes. "
    "Use the Write or Edit tool for file content."
)
MUTATING_VERB_RE = re.compile(
    r"\b(?:tee|cp|mv|ln|rm|truncate|chmod|chown|dd|shred|unlink)\b|\bsed\s+-i", re.IGNORECASE
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

RULES: dict[str, tuple[str, str]] = {
    "install_without_sandbox_home": (
        "Installer or merge script aimed at the real HOME",
        "Re-run it with a sandbox HOME such as HOME=\"$(mktemp -d)\"."),
    "commit_gate_bypass": (
        "Commit skips the pre-commit gate",
        "Drop the no-verify flag and repair the reported finding."),
    "cap_override": (
        "Discipline cap or escape overridden on the command line",
        "Fix the code shape instead of raising the cap."),
    "state_deletion": (
        "Watcher state or gate config deleted",
        "Leave the state in place and repair the reported finding."),
    "state_mutation": (
        "Watcher state or gate config mutated",
        "Leave watcher state under host control and repair the reported finding."),
    "live_client_surface": (
        "Shell command mutates a live client install",
        "Change the repo source and reinstall instead of editing the live install."),
}


def run(payload: dict, config: dict | None = None) -> dict:
    """Judge a pending Bash command, blocking rather than passing it through when the gate itself cannot decide."""
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
    findings = command_findings(command, cfg) + target_findings(command, cfg)
    if findings:
        reason, _ = compact_block(findings, cfg)
        _record(payload, cfg, turn_id, findings, started)
        return deny(reason)
    size = oversize_write(command)
    if size is not None:
        return deny(OVERSIZE_WRITE.format(size=size, cap=BASH_WRITE_CAP))
    content = write_findings(command, cfg)
    if not content:
        return allow()
    return _verdict(_record(payload, cfg, turn_id, content, started), cfg)


def _record(payload: dict, cfg: dict, turn_id: str, findings: list[dict], started: float) -> list[tuple[dict, str]]:
    return record_findings(
        session_id=str(payload.get("session_id") or ""), hook="pre_bash",
        event="PreToolUse", findings=findings, turn_id=turn_id,
        tool_use_id=str(payload.get("tool_use_id") or ""),
        duration_ms=int((time.monotonic() - started) * 1000),
        root=cfg.get("ledger_root"), config=cfg,
    )


def _verdict(decisions: list[tuple[dict, str]], cfg: dict) -> dict:
    kind, reason = reporting.verdict_message(decisions, cfg)
    if kind == "block":
        return deny(reason)
    if kind == "observe":
        return advise(reason, "PreToolUse")
    return allow()


def command_findings(command: str, config: dict | None = None, home: str | os.PathLike[str] | None = None) -> list[dict]:
    """Return every blocking finding for one Bash command string, judged per shell segment."""
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
    if any(_mutates_live_client(segment, home) for segment in segments):
        hits.append("live_client_surface")
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
    """Pair every write target with its text, holding the targets whose text is unknowable at None rather than dropping them."""
    targets: dict[str, str | None] = {path: None for path in _mutation_paths(command)}
    targets.update({path: None for path in write_paths(command)})
    targets.update(dict(write_targets(command)))
    return targets


def oversize_write(command: str) -> int | None:
    """Return the largest knowable Bash write size when it exceeds the hard cap."""
    sizes = [len(text) for _, text in write_targets(command)]
    for line, _, raw_bodies in _logical_lines(command):
        if not any(_write_paths(segment) for segment in _segments(line)):
            continue
        sizes.extend(len(body) for body in raw_bodies)
    oversized = [size for size in sizes if size > BASH_WRITE_CAP]
    return max(oversized) if oversized else None


def _mutation_paths(command: str) -> list[str]:
    return [path for segment in _segments(command) if _is_mutating(segment) for path in _segment_paths(segment)]


def write_findings(command: str, config: dict | None = None) -> list[dict]:
    """Scan literal shell writes, because PostToolUse never matches Bash and this content would otherwise land unread."""
    findings = []
    for path, text in write_targets(command):
        body = scannable_text(text, config or {})
        if body is None:
            continue
        for finding in scan_all(path, body, config):
            item = dict(finding)
            item["path"] = path
            findings.append(item)
    return findings


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
    words = _words(segment)
    if not any(_basename(word) in STATE_DELETE_VERBS for word in words):
        return False
    return any(STATE_TARGET_RE.search(word) for word in words)


def _mutates_state(segment: list[str]) -> bool:
    return _is_mutating(segment) and any(
        STATE_TARGET_RE.search(word) for word in _words(segment)
    )



def _is_mutating(segment: list[str]) -> bool:
    """Report the mutating shell forms, so that a read of a protected path stays allowed."""
    return bool(_redirect_paths(segment)) or bool(MUTATING_VERB_RE.search(_segment_text(segment)))



def _mutates_live_client(segment: list[str], home: str | os.PathLike[str] | None) -> bool:
    """Require the mutating form and the live client target inside the same segment, so that a read stays allowed."""
    if not _is_mutating(segment):
        return False
    return any(is_live_client_path(path, home) for path in _mutation_targets(segment))


DESTINATION_LAST_ARG_VERBS = frozenset({"cp", "mv", "ln", "sed"})
DESTINATION_ALL_ARGS_VERBS = frozenset({"rm", "unlink", "shred", "truncate", "chmod", "chown"})
TARGET_DIR_VERBS = frozenset({"cp", "mv", "ln"})
TARGET_DIR_FLAGS = frozenset({"-t", "--target-directory"})


def _mutation_targets(segment: list[str]) -> list[str]:
    """Because a copy's source argument is not its destination, a protected path used as input must not block a read."""
    targets = [_expand_home(path) for path in _write_paths(segment)]
    index = _command_word_index(segment)
    if index >= len(segment):
        return [path for path in targets if _is_file_target(path)]
    verb = _basename(segment[index])
    args = segment[index + 1:]
    target_dir = _target_directory(args) if verb in TARGET_DIR_VERBS else None
    if target_dir is not None:
        targets.append(_expand_home(target_dir))
    raw_args = [token for token in _drop_target_dir(args) if not _bare(token).startswith("-")]
    if verb == "dd":
        targets.extend(_expand_home(_bare(token)) for token in raw_args if _bare(token).startswith("of="))
    elif verb in DESTINATION_LAST_ARG_VERBS and raw_args and target_dir is None:
        targets.append(_expand_home(_bare(raw_args[-1])))
    elif verb in DESTINATION_ALL_ARGS_VERBS:
        targets.extend(_expand_home(_bare(token)) for token in raw_args)
    return [path for path in targets if _is_file_target(path)]


def _target_directory(args: list[str]) -> str | None:
    """Because -t/--target-directory names the real destination for GNU cp, mv, and ln, the last positional argument must defer to it."""
    for position, token in enumerate(args):
        bare = _bare(token)
        if bare.startswith("--target-directory="):
            return bare.partition("=")[2]
        if bare in TARGET_DIR_FLAGS and position + 1 < len(args):
            return _bare(args[position + 1])
    return None


def _drop_target_dir(args: list[str]) -> list[str]:
    kept = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        bare = _bare(token)
        if bare.startswith("--target-directory="):
            continue
        if bare in TARGET_DIR_FLAGS:
            skip_next = True
            continue
        kept.append(token)
    return kept



def _finding(rule: str, command: str) -> dict:
    detail, action = RULES[rule]
    return {
        "family": "self_protection",
        "rule": rule,
        "line": 1,
        "detail": detail,
        "force": True,
        "snippet": command.strip()[:180],
        "action": action,
    }



def _command(payload: dict) -> str:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    command = tool_input.get("command") or tool_input.get("cmd") or ""
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return str(command)


if __name__ == "__main__":
    write_payload(claude_pretool_response(run(read_payload())))
