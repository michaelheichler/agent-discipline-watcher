"""Bash command policy: block shell routes around the discipline gates before the command runs."""
from __future__ import annotations

import os
import re
import shlex
import time
from pathlib import PurePosixPath

from lib.config import effective_config
from lib.hookio import advise, allow, deny, read_payload, write_payload
from lib.protected import authorized, is_live_client_path, path_findings
from lib.reporting import compact_block, record_findings, run_with_ledger
from lib.scanner import scan_all, scannable_text

# The lookbehind drops 2> and the tail of 2>>, because a stderr redirect writes no target file.
WRITE_REDIRECT_RE = re.compile(r"(?<![2>])>")
REDIRECT_HEAD_RE = re.compile(r"^\d*>>?")
HEREDOC_RE = re.compile(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|([A-Za-z_][A-Za-z0-9_]*))")
DYNAMIC_RE = re.compile(r"[$`]")
LITERAL_PRODUCERS = frozenset({"echo", "printf"})
ECHO_FLAGS = frozenset({"-n", "-e", "-E", "-ne", "-en"})
BASH_WRITE_CAP = 100
OVERSIZE_WRITE = (
    "Shell write of {size} characters exceeds the {cap}-character cap for Bash file writes. "
    "Use the Write or Edit tool for file content."
)
UNDECIDABLE = (
    "agent-discipline-watcher could not evaluate this command and blocked it rather than letting it through. "
    "Repair the gate config and retry. Cause: "
)
OBSERVE_PREFIX = (
    "agent-discipline-watcher is observing these, not blocking. "
    "Judge each one and either repair it or state why it stands.\n"
)
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
    "ADW_SENTENCE_WORD_CAP", "ADW_LIST_ITEM_CAP",
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
    """Judge a pending Bash command, blocking rather than passing it through when the gate itself cannot decide."""
    try:
        return _run(payload, config)
    except Exception as exc:
        return deny(UNDECIDABLE + str(exc))


def _run(payload: dict, config: dict | None) -> dict:
    cfg = effective_config(config, payload.get("cwd") or None)
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
    blocking = [finding for finding, outcome in decisions if outcome == "block"]
    if blocking:
        reason, _ = compact_block(blocking, cfg)
        return deny(reason)
    observed = [finding for finding, outcome in decisions if outcome == "would_block"]
    if not observed:
        return allow()
    reason, _ = compact_block(observed, cfg)
    return advise(OBSERVE_PREFIX + reason, "PreToolUse")


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


def write_paths(command: str) -> list[str]:
    """Return every literal write target, including those whose content this parser cannot read."""
    return [
        path
        for line, _, _ in _logical_lines(command)
        for segment in _segments(line)
        for path in _write_paths(segment)
    ]


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
        body = scannable_text(text, config)
        if body is None:
            continue
        for finding in scan_all(path, body, config):
            item = dict(finding)
            item["path"] = path
            findings.append(item)
    return findings


def write_targets(command: str) -> list[tuple[str, str]]:
    """Pair each shell write target with the literal text it receives, skipping any write whose text is not knowable here."""
    rows: list[tuple[str, str]] = []
    for line, bodies, _ in _logical_lines(command):
        rows.extend(_line_writes(line, bodies))
    return rows


def _logical_lines(command: str) -> list[tuple[str, list[str | None], list[str]]]:
    lines = command.splitlines()
    rows: list[tuple[str, list[str | None], list[str]]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        bodies: list[str | None] = []
        raw_bodies: list[str] = []
        for match in HEREDOC_RE.finditer(line):
            raw_body, dynamic, index = _heredoc_body(lines, index, match)
            raw_bodies.append(raw_body)
            bodies.append(None if dynamic else raw_body)
        rows.append((line, bodies, raw_bodies))
    return rows


def _heredoc_body(lines: list[str], index: int, match: re.Match) -> tuple[str, bool, int]:
    strip, delimiter = match.group(1) == "-", match.group(2) or match.group(3) or match.group(4)
    collected: list[str] = []
    while index < len(lines):
        raw = lines[index]
        index += 1
        line = raw.lstrip("\t") if strip else raw
        if line.rstrip() == delimiter:
            body = "\n".join(collected)
            expandable = match.group(4) is not None
            return body, expandable and bool(DYNAMIC_RE.search(body)), index
        collected.append(line)
    return "\n".join(collected), True, index



def _line_writes(line: str, bodies: list[str | None]) -> list[tuple[str, str]]:
    segments = _segments(line)
    targets = [path for segment in segments for path in _write_paths(segment)]
    if not targets:
        return []
    contents = list(bodies) if bodies else _literal_contents(segments)
    if not contents or None in contents:
        return []
    if len(contents) == 1:
        return [(path, contents[0]) for path in targets]
    if len(contents) == len(targets):
        return list(zip(targets, contents))
    return []



def _write_paths(segment: list[str]) -> list[str]:
    paths = _redirect_paths(segment)
    index = _command_word_index(segment)
    if index < len(segment) and _basename(segment[index]) == "tee":
        paths.extend(_bare(token) for token in segment[index + 1:] if not _bare(token).startswith("-"))
    return [path for path in paths if _is_file_target(path)]



def _redirect_paths(segment: list[str]) -> list[str]:
    paths = []
    for index, token in enumerate(segment):
        match = REDIRECT_HEAD_RE.match(token)
        if _is_quoted(token) or not match or not WRITE_REDIRECT_RE.search(token):
            continue
        rest = token[match.end():]
        if not rest and index + 1 < len(segment):
            rest = segment[index + 1]
        paths.append(_bare(rest))
    return paths



def _is_file_target(path: str) -> bool:
    return bool(path) and not path.startswith("&") and not path.startswith("/dev/")



def _command_word_index(segment: list[str]) -> int:
    """Step past env assignments and wrapper interpreters, because the word after them is what actually runs."""
    index = 0
    while index < len(segment):
        token = segment[index]
        if _is_quoted(token):
            return index
        name, separator, _ = token.partition("=")
        if (separator and name) or _basename(token) in INTERPRETERS:
            index += 1
            continue
        return index
    return len(segment)



def _literal_contents(segments: list[list[str]]) -> list[str | None]:
    contents = []
    for segment in segments:
        index = _command_word_index(segment)
        if index < len(segment) and _basename(segment[index]) in LITERAL_PRODUCERS:
            contents.append(_producer_text(segment[index + 1:]))
    return contents



def _producer_text(args: list[str]) -> str | None:
    words: list[str] = []
    skip = False
    for token in args:
        if skip:
            skip = False
            continue
        match = REDIRECT_HEAD_RE.match(token)
        if match and not _is_quoted(token):
            skip = not token[match.end():]
            continue
        if DYNAMIC_RE.search(token) and not (token.startswith("'") and token.endswith("'")):
            return None
        if not words and _bare(token) in ECHO_FLAGS:
            continue
        words.append(_bare(token))
    return " ".join(words).replace("\\n", "\n").replace("\\t", "\t")



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



def _is_mutating(segment: list[str]) -> bool:
    """Report the mutating shell forms, so that a read of a protected path stays allowed."""
    text = _segment_text(segment)
    return bool(WRITE_REDIRECT_RE.search(text) or MUTATING_VERB_RE.search(text))



def _mutates_live_client(segment: list[str], home: str | os.PathLike[str] | None) -> bool:
    """Require the mutating form and the live client target inside the same segment, so that a read stays allowed."""
    if not _is_mutating(segment):
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
