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
SEPARATORS = frozenset({"&&", "||", ";", "|", "(", ")"})
SANDBOX_HOME_RE = re.compile(r"\bHOME\s*=")
NO_VERIFY_RE = re.compile(r"\bgit\s+commit\b[^\n]*?(?:--no-verify\b|\s-n(?=\s|$))")
CAP_OVERRIDE_RE = re.compile(
    r"\b(?:CLEANCODER_FUNC_BLOCK_LINES|CLEANCODER_FILE_BLOCK_LINES"
    r"|ADW_MAX_SCAN_BYTES|ADW_ALLOW_PROTECTED_EDIT)\s*="
)
STATE_DELETE_RE = re.compile(
    r"\b(?:rm|unlink|shred)\b[^\n]*?(?:\.agent-discipline\b|agent-discipline/(?:state|ledger))"
)
HOME_TOKEN_RE = re.compile(r"^(?:~|\$HOME|\$\{HOME\})(?=/|$)")
# Strips the of= and if= style operands used by dd, because the path hides behind the key.
OPERAND_PREFIX_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

RULES = (
    ("install_without_sandbox_home",
     "Installer or merge script aimed at the real HOME",
     "Re-run it with a sandbox HOME such as HOME=\"$(mktemp -d)\"."),
    ("commit_gate_bypass",
     "Commit skips the pre-commit gate",
     "Drop --no-verify and repair the reported finding."),
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
    """Return every blocking finding for one Bash command string."""
    if not command or authorized(config):
        return []
    hits = []
    if _runs_installer(command) and not SANDBOX_HOME_RE.search(command):
        hits.append("install_without_sandbox_home")
    if NO_VERIFY_RE.search(command):
        hits.append("commit_gate_bypass")
    if CAP_OVERRIDE_RE.search(command):
        hits.append("cap_override")
    if STATE_DELETE_RE.search(command):
        hits.append("state_deletion")
    if _mutates_live_client(command, home):
        hits.append("live_client_surface")
    return [_finding(rule, command) for rule in hits]


def _runs_installer(command: str) -> bool:
    """Report an installer only when it sits in command position, so that a quoted mention never blocks."""
    tokens = _shell_tokens(command)
    for index, token in enumerate(tokens):
        if _basename(token) not in INSTALLER_NAMES:
            continue
        if index == 0:
            return True
        previous = tokens[index - 1]
        if previous in SEPARATORS or _basename(previous) in INTERPRETERS:
            return True
    return False


def _basename(token: str) -> str:
    return PurePosixPath(token.strip("\"',")).name


def _shell_tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return command.split()


def _mutates_live_client(command: str, home: str | os.PathLike[str] | None) -> bool:
    """Require both a mutating form and a live client target, so that reading a live file stays allowed."""
    if not (WRITE_REDIRECT_RE.search(command) or MUTATING_VERB_RE.search(command)):
        return False
    return any(is_live_client_path(token, home) for token in _path_tokens(command))


def _path_tokens(command: str) -> list[str]:
    """Split a command into candidate path tokens, falling back to whitespace splitting when quoting is unbalanced."""
    try:
        raw = shlex.split(command, posix=True)
    except ValueError:
        raw = re.split(r"[\s;&|<>()]+", command)
    tokens = []
    for token in raw:
        for part in re.split(r"[<>|;&]+", token):
            expanded = _expand_home(part.strip().strip("\"'"))
            if expanded:
                tokens.append(expanded)
    return tokens


def _expand_home(token: str) -> str:
    token = OPERAND_PREFIX_RE.sub("", token, count=1)
    match = HOME_TOKEN_RE.match(token)
    if not match:
        return token
    return "~" + token[match.end():]


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
