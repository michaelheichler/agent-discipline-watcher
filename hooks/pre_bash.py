"""Bash command policy: block shell routes around the discipline gates before the command runs."""
from __future__ import annotations

import os
import re
import shlex
from pathlib import PurePosixPath

from lib.config import effective_config
from lib.hookio import allow, deny, read_payload, write_payload
from lib.protected import authorized, is_live_client_path
from lib.reporting import compact_block

# The lookbehind drops 2> and the tail of 2>>, because a stderr redirect writes no target file.
WRITE_REDIRECT_RE = re.compile(r"(?<![2>])>")
MUTATING_VERB_RE = re.compile(
    r"\b(?:tee|cp|mv|ln|rm|truncate|chmod|chown|dd|shred|unlink)\b|\bsed\s+-i", re.IGNORECASE
)
INSTALLER_NAMES = frozenset({
    "install.sh", "merge-claude-settings.py", "merge-codex-config.py", "merge-pi-settings.py",
})
# Matched only in command position, because naming a script inside a quoted string is not running it.
INTERPRETERS = frozenset({
    "python", "python3", "sh", "bash", "zsh", "dash", "command", "env", "exec", "sudo", "time", "nohup",
})
SEPARATORS = frozenset({"&&", "||", ";", "|", "&", "(", ")"})
CAP_VARS = frozenset({
    "CLEANCODER_FUNC_BLOCK_LINES", "CLEANCODER_FILE_BLOCK_LINES",
    "ADW_FUNC_BLOCK_LINES", "ADW_FILE_BLOCK_LINES",
    "ADW_MAX_SCAN_BYTES", "ADW_ALLOW_PROTECTED_EDIT",
})
NO_VERIFY_FLAGS = frozenset({"--no-verify", "-n"})
STATE_DELETE_VERBS = frozenset({"rm", "unlink", "shred"})
STATE_TARGET_RE = re.compile(r"\.agent-discipline\b|agent-discipline/(?:state|ledger)")
HOME_TOKEN_RE = re.compile(r"^(?:~|\$HOME|\$\{HOME\})(?=/|$)")
# Strips the of= and if= style operands used by dd, because the path hides behind the key.
OPERAND_PREFIX_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

RULES = (
    ("install_without_sandbox_home",
     "Installer or merge script aimed at the real HOME",
     "Re-run it with a sandbox HOME such as HOME=\"$(mktemp -d)\"."),
    ("commit_gate_bypass",
     "Commit skips the pre-commit gate",
     "Drop the no-verify flag and repair the reported finding."),
    ("cap_override",
     "Discipline cap or escape overridden on the command line",
     "Fix the code shape instead of raising the cap."),
    ("state_deletion",
     "Watcher state or gate config deleted",
     "Leave the state in place and repair the reported finding."),
    ("live_client_surface",
     "Shell command mutates a live client install",
     "Change the repo source and reinstall instead of editing the live install."),
)


def run(payload: dict, config: dict | None = None) -> dict:
    command = _command(payload)
    if not command:
        return allow()
    cfg = effective_config(config, payload.get("cwd") or None)
    findings = command_findings(command, cfg)
    if not findings:
        return allow()
    reason, _ = compact_block(findings, cfg)
    return deny(reason)


def command_findings(command: str, config: dict | None = None, home: str | os.PathLike[str] | None = None) -> list[dict]:
    """Return every blocking finding for one Bash command string, judged per shell segment."""
    if not command or authorized(config):
        return []
    segments = _segments(command)
    sandboxed = any(_sets_home(segment) for segment in segments)
    hits = []
    if not sandboxed and any(_runs_installer(segment) for segment in segments):
        hits.append("install_without_sandbox_home")
    if any(_skips_commit_gate(segment) for segment in segments):
        hits.append("commit_gate_bypass")
    if any(_overrides_cap(segment) for segment in segments):
        hits.append("cap_override")
    if any(_deletes_state(segment) for segment in segments):
        hits.append("state_deletion")
    if any(_mutates_live_client(segment, home) for segment in segments):
        hits.append("live_client_surface")
    return [_finding(rule, command) for rule in hits]


def _segments(command: str) -> list[list[str]]:
    """Split into shell segments of raw tokens, keeping quotes so that quoted text can be masked later."""
    try:
        lexer = shlex.shlex(command, posix=False, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in SEPARATORS:
            if current:
                segments.append(current)
            current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _is_quoted(token: str) -> bool:
    return len(token) > 1 and token[0] in "\"'" and token[-1] == token[0]


def _bare(token: str) -> str:
    return token[1:-1] if _is_quoted(token) else token


def _segment_text(segment: list[str]) -> str:
    """Join a segment with quoted tokens blanked, because text inside quotes is data rather than shell syntax."""
    return " ".join("''" if _is_quoted(token) else token for token in segment)


def _leading_assignments(segment: list[str]) -> list[str]:
    """Return the env assignments that prefix a command, stopping at the first real word."""
    names = []
    for token in segment:
        if _is_quoted(token):
            break
        name, separator, _ = token.partition("=")
        if not separator or not name:
            break
        names.append(name)
    return names


def _sets_home(segment: list[str]) -> bool:
    return "HOME" in _leading_assignments(segment)


def _overrides_cap(segment: list[str]) -> bool:
    return any(name in CAP_VARS for name in _leading_assignments(segment))


def _words(segment: list[str]) -> list[str]:
    return [_bare(token) for token in segment]


def _runs_installer(segment: list[str]) -> bool:
    """Report an installer only in command position, so that a quoted mention never blocks."""
    for index, token in enumerate(segment):
        if _is_quoted(token) or _basename(token) not in INSTALLER_NAMES:
            continue
        if index == 0:
            return True
        if _basename(segment[index - 1]) in INTERPRETERS:
            return True
    return False


def _skips_commit_gate(segment: list[str]) -> bool:
    """Match the no-verify flags only as bare argument tokens of a git commit in this segment."""
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


def _mutates_live_client(segment: list[str], home: str | os.PathLike[str] | None) -> bool:
    """Require the mutating form and the live client target inside the same segment, so that a read stays allowed."""
    text = _segment_text(segment)
    if not (WRITE_REDIRECT_RE.search(text) or MUTATING_VERB_RE.search(text)):
        return False
    return any(is_live_client_path(path, home) for path in _segment_paths(segment))


def _segment_paths(segment: list[str]) -> list[str]:
    paths = []
    for token in segment:
        for part in re.split(r"[<>|;&]+", _bare(token)):
            expanded = _expand_home(part.strip())
            if expanded:
                paths.append(expanded)
    return paths


def _expand_home(token: str) -> str:
    token = OPERAND_PREFIX_RE.sub("", token, count=1)
    match = HOME_TOKEN_RE.match(token)
    if not match:
        return token
    return "~" + token[match.end():]


def _basename(token: str) -> str:
    return PurePosixPath(_bare(token).strip(",")).name


def _finding(rule: str, command: str) -> dict:
    detail, action = next((row[1], row[2]) for row in RULES if row[0] == rule)
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
    write_payload(run(read_payload()))
