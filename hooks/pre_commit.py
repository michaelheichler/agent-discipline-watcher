from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

import lib.reporting as reporting
import lib.rewrite as rewrite
from lib.baseline import strip_against
from lib.config import effective_config
from lib.hookio import PARSE_FAILURE, advise, allow, deny, read_payload, write_payload
from lib.reporting import record_findings, run_with_ledger, verdict_message
from lib.scanner import scan_all, scannable_text

# Suffixed so that scanner._is_prose treats the message as prose and the english family reaches it.
COMMIT_MESSAGE_PATH = "commit_message.md"


UNDECIDABLE = (
    "agent-discipline-watcher could not evaluate this commit and blocked it rather than letting it through. "
    "Repair the gate config and retry. Cause: "
)


def run(
    payload: dict,
    config: dict | None = None,
    ledger_root: str | os.PathLike[str] | None = None,
    state_root: str | os.PathLike[str] | None = None,
) -> dict:
    """Scan the staged tree behind a pending commit, blocking rather than letting it through when the gate cannot decide."""
    try:
        if payload is PARSE_FAILURE:
            return deny(UNDECIDABLE + "unreadable hook payload")
        return _run(payload, config, ledger_root, state_root)
    except Exception as exc:
        return deny(UNDECIDABLE + str(exc))


def _run(
    payload: dict,
    config: dict | None,
    ledger_root: str | os.PathLike[str] | None,
    state_root: str | os.PathLike[str] | None,
) -> dict:
    return run_with_ledger(
        hook="pre_commit",
        payload=payload,
        gate=lambda turn_id: _gate(payload, config, turn_id, ledger_root),
        ledger_root=ledger_root,
        state_root=state_root,
    )


def _gate(payload: dict, config: dict | None, turn_id: str, ledger_root) -> dict:
    started = time.monotonic()
    command = _bash_command(payload)
    cwd = Path(payload.get("cwd") or os.getcwd())
    commit_cwds = _commit_cwds(command, cwd)
    if not commit_cwds:
        return allow()
    cfg = effective_config(config, cwd)
    new_command, message_changes = _rewrite_commit_messages(command, cfg)
    findings = _staged_findings(commit_cwds, config)
    message_findings = _message_findings(new_command, cfg)
    findings.extend(message_findings)
    if not findings and not message_changes:
        return allow()
    decisions = record_findings(
        session_id=str(payload.get("session_id") or ""), hook="pre_commit",
        event="PreCommit", findings=findings, turn_id=turn_id,
        tool_use_id=str(payload.get("tool_use_id") or ""),
        duration_ms=int((time.monotonic() - started) * 1000),
        root=ledger_root, config=cfg,
    )
    return _gate_response(
        payload, command, new_command, message_changes, message_findings, decisions, cfg
    )


def _gate_response(
    payload: dict, command: str | list[str], new_command: str | list[str],
    message_changes: list[dict], message_findings: list[dict],
    decisions: list[tuple[dict, str]], cfg: dict,
) -> dict:
    kind, message = verdict_message(decisions, cfg)
    if kind == "block":
        return deny(message)
    flagged = [finding for finding, outcome in decisions if outcome == "must_fix"]
    if message_changes or any(finding in message_findings for finding in flagged):
        notice = reporting.correction_notice(message_changes, flagged, cfg)
        if message_changes:
            notice = "agent-discipline-watcher rewrote the commit message before the commit ran.\n" + notice
        if kind == "observe":
            notice = "\n".join(part for part in (notice, message) if part)
        return _correction_response(payload, command, new_command, notice)
    return advise(message, "PreToolUse") if kind in {"must_fix", "observe"} else allow()


def _correction_response(
    payload: dict, command: str | list[str], new_command: str | list[str], notice: str
) -> dict:
    response = advise(notice, "PreToolUse")
    if new_command != command:
        response["hookSpecificOutput"]["updatedInput"] = _updated_tool_input(payload, new_command)
    return response


def _staged_findings(commit_cwds: list[Path], config: dict | None) -> list[dict]:
    findings = []
    for commit_cwd in commit_cwds:
        repo = _repo_root(commit_cwd)
        if repo is None:
            continue
        cfg = effective_config(config, commit_cwd)
        findings.extend(_repo_findings(repo, cfg))
    return findings


def _repo_findings(repo: Path, cfg: dict) -> list[dict]:
    findings = []
    for path in _staged(repo):
        text = _staged_text(repo, path)
        if text is None or scannable_text(text, cfg) is None:
            continue
        owned = strip_against(_head_text(repo, path), path, scan_all(path, text, cfg), cfg)
        for finding in owned:
            item = dict(finding)
            item["path"] = path
            findings.append(item)
    return findings


def _head_text(repo: Path, path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "show", "HEAD:" + path], cwd=repo, text=True,
            capture_output=True, check=True, timeout=30, errors="replace",
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout


def _message_findings(command: str | list[str], cfg: dict) -> list[dict]:
    """Scan the message the agent typed, because a commit's prose ships with the same authority as its code."""
    # Blank line between parts, because git itself joins repeated -m values as paragraphs.
    text = "\n\n".join(_commit_messages(command))
    if not text:
        return []
    return [
        {**finding, "path": COMMIT_MESSAGE_PATH}
        for finding in scan_all(COMMIT_MESSAGE_PATH, text, cfg)
    ]


def _rewrite_commit_messages(
    command: str | list[str], cfg: dict
) -> tuple[str | list[str], list[dict]]:
    if isinstance(command, list):
        return _rewrite_list_commit_messages(command, cfg)
    return _rewrite_string_commit_messages(command, cfg)


def _rewrite_string_commit_messages(command: str, cfg: dict) -> tuple[str, list[dict]]:
    changes: list[dict] = []
    replacements: list[tuple[int, int, str]] = []
    message_line = 1
    for segment in _raw_segments(command):
        values = [_raw_word_value(raw) for raw, _start, _end in segment]
        for word_index, form, value in _message_occurrences(values):
            raw, start, end = segment[word_index]
            if _is_ansi_c_quoted(raw, form):
                continue
            result, result_changes, message_line = _rewrite_message_value(
                value, message_line, cfg
            )
            changes.extend(result_changes)
            if result == value:
                continue
            prefix = "" if form == "separate" else "--message=" if form == "equals" else "-m"
            replacement = shlex.quote(result) if form == "separate" else prefix + shlex.quote(result)
            replacements.append((start, end, replacement))
    updated = command
    for start, end, replacement in sorted(replacements, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    return (updated if replacements else command), changes


def _rewrite_list_commit_messages(
    command: list[str], cfg: dict
) -> tuple[list[str], list[dict]]:
    updated = list(command)
    changes: list[dict] = []
    message_line = 1
    for segment in _indexed_list_segments(command):
        values = [value for _index, value in segment]
        for word_index, form, value in _message_occurrences(values):
            result, result_changes, message_line = _rewrite_message_value(
                value, message_line, cfg
            )
            changes.extend(result_changes)
            if result == value:
                continue
            list_index = segment[word_index][0]
            prefix = "" if form == "separate" else "--message=" if form == "equals" else "-m"
            updated[list_index] = result if form == "separate" else prefix + result
    return (updated if updated != command else command), changes


def _rewrite_message_value(
    value: str, message_line: int, cfg: dict
) -> tuple[str, list[dict], int]:
    result = rewrite.rewrite_text(COMMIT_MESSAGE_PATH, value, cfg)
    families = {
        finding.get("rule"): finding.get("family", "")
        for finding in scan_all(COMMIT_MESSAGE_PATH, value, cfg)
    }
    changes = []
    for change in result.changes:
        item = {
            **change,
            "path": COMMIT_MESSAGE_PATH,
            "family": families.get(change.get("rule"), ""),
        }
        if isinstance(item.get("line"), int):
            item["line"] += message_line - 1
        changes.append(item)
    next_line = message_line + (result.text.count("\n") + 2 if result.text else 2)
    return result.text, changes, next_line


def _updated_tool_input(payload: dict, command: str | list[str]) -> dict:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    updated = dict(tool_input)
    key = next(
        (name for name in ("command", "cmd", "input") if name in tool_input),
        "command",
    )
    updated[key] = list(command) if isinstance(command, list) else command
    return updated


def _commit_messages(command: str | list[str]) -> list[str]:
    messages: list[str] = []
    for segment in _segments(command):
        tokens = _unwrap_command(_strip_group_tokens(segment))
        messages.extend(_messages_after_commit(tokens))
    return messages


def _messages_after_commit(tokens: list[str]) -> list[str]:
    if len(tokens) < 2 or tokens[0] != "git" or "commit" not in tokens:
        return []
    return _message_values(tokens[tokens.index("commit") + 1:])


def _message_occurrences(tokens: list[str]) -> list[tuple[int, str, str]]:
    start = _unwrap_start(tokens)
    tokens = tokens[start:]
    if len(tokens) < 2 or tokens[0] != "git" or "commit" not in tokens:
        return []
    commit_index = tokens.index("commit")
    return [
        (start + commit_index + 1 + index, form, value)
        for index, form, value in _message_positions(tokens[commit_index + 1:])
    ]


def _message_positions(tokens: list[str]) -> list[tuple[int, str, str]]:
    values: list[tuple[int, str, str]] = []
    cursor = 0
    while cursor < len(tokens):
        token = tokens[cursor]
        if token in {"-m", "--message"} or _is_message_bundle(token):
            if cursor + 1 < len(tokens):
                values.append((cursor + 1, "separate", tokens[cursor + 1]))
            cursor += 2
            continue
        name, separator, inline = token.partition("=")
        if separator and name == "--message":
            values.append((cursor, "equals", inline))
        elif token.startswith("-m") and len(token) > 2:
            values.append((cursor, "short_inline", token[2:]))
        cursor += 1
    return values


_BOOLEAN_BUNDLE_CHARS = frozenset("anqvoe")  # only genuinely no-value git commit short flags: -a -n -q -v -o -e


def _is_message_bundle(token: str) -> bool:
    if not token.startswith("-") or token.startswith("--") or len(token) <= 2:
        return False
    if token[-1] != "m":
        return False
    return all(char in _BOOLEAN_BUNDLE_CHARS for char in token[1:-1])


def _message_values(tokens: list[str]) -> list[str]:
    return [value for _index, _form, value in _message_positions(tokens)]


def _raw_segments(command: str) -> list[list[tuple[str, int, int]]]:
    segments: list[list[tuple[str, int, int]]] = []
    current: list[tuple[str, int, int]] = []
    for raw in _raw_words(command):
        if raw[0] in {"&&", "||", ";", "|", "(", ")"}:
            segments.append(current)
            segments.append([raw])
            current = []
        else:
            current.append(raw)
    segments.append(current)
    return segments


def _raw_words(command: str) -> list[tuple[str, int, int]]:
    tokens = _positioned_tokens(command)
    if not tokens:
        return []
    words: list[tuple[str, int, int]] = []
    index = 0
    while index < len(tokens):
        raw, start, end = tokens[index]
        if raw in {"&&", "||", ";", "|", "(", ")"}:
            words.append((raw, start, end))
            index += 1
            continue
        word_end = _shell_word_end(command, start)
        index += 1
        while index < len(tokens) and tokens[index][1] < word_end:
            index += 1
        words.append((command[start:word_end], start, word_end))
    return words


def _positioned_tokens(command: str) -> list[tuple[str, int, int]]:
    try:
        lexer = shlex.shlex(command, posix=False, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        tokens: list[tuple[str, int, int]] = []
        cursor = 0
        for token in lexer:
            start = command.index(token, cursor)
            end = start + len(token)
            tokens.append((command[start:end], start, end))
            cursor = end
        return tokens
    except (ValueError, IndexError):
        return []


def _shell_word_end(command: str, start: int) -> int:
    quote = ""
    cursor = start
    while cursor < len(command):
        char = command[cursor]
        if quote:
            if char == "\\" and quote == '"' and cursor + 1 < len(command):
                cursor += 2
                continue
            if char == quote:
                quote = ""
            cursor += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "\\" and cursor + 1 < len(command):
            cursor += 2
            continue
        elif char.isspace() or char in ";&|()":
            break
        cursor += 1
    return cursor


def _raw_word_value(raw: str) -> str:
    try:
        values = shlex.split(raw)
    except ValueError:
        values = []
    if len(values) == 1:
        return values[0]
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        return raw[1:-1]
    return raw


def _is_ansi_c_quoted(raw: str, form: str) -> bool:
    if form == "separate":
        value = raw
    elif form == "equals":
        value = raw.partition("=")[2]
    else:
        value = raw[2:]
    return value.startswith("$'")


PATH_FLAGS = frozenset({"-C", "--work-tree", "--git-dir"})


def _bash_command(payload: dict) -> str | list[str]:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    for key in ("command", "cmd", "input"):
        if key in tool_input:
            command = tool_input[key]
            return list(command) if isinstance(command, list) else str(command)
    return ""


def _commit_cwds(command: str | list[str], cwd: Path) -> list[Path]:
    current = cwd
    stack: list[Path] = []
    commits: list[Path] = []
    for segment in _segments(command):
        if not segment:
            continue
        if segment == ["("]:
            stack.append(current)
            continue
        if segment == [")"]:
            current = stack.pop() if stack else current
            continue
        segment = _strip_group_tokens(segment)
        if not segment:
            continue
        if segment[0] == "cd" and len(segment) >= 2:
            current = _resolve_cwd(current, segment[1])
            continue
        git_cwd = _git_commit_cwd(segment, current)
        if git_cwd is not None:
            commits.append(git_cwd)
    return commits


def _segments(command: str | list[str]) -> list[list[str]]:
    if isinstance(command, list):
        return [[token for _index, token in segment] for segment in _indexed_list_segments(command)]
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        parts = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for part in parts:
        if part in {"&&", "||", ";", "|", "(", ")"}:
            segments.append(current)
            segments.append([part])
            current = []
            continue
        current.append(part)
    segments.append(current)
    return segments


def _indexed_list_segments(command: list[str]) -> list[list[tuple[int, str]]]:
    segments: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for index, token in enumerate(command):
        if token in {"&&", "||", ";", "|", "(", ")"}:
            segments.append(current)
            segments.append([(index, token)])
            current = []
            continue
        current.append((index, token))
    segments.append(current)
    return segments


def _flag_cwd(flag: str, current: Path, value: str) -> Path:
    resolved = _resolve_cwd(current, value)
    if flag == "--git-dir" and resolved.name == ".git":
        return resolved.parent
    return resolved


def _skip_git_flag(segment: list[str], cursor: int, current: Path) -> tuple[int, Path, bool] | None:
    token = segment[cursor]
    if token.startswith("-C") and len(token) > 2:
        return cursor + 1, _resolve_cwd(current, token[2:]), False
    name, separator, inline = token.partition("=")
    if separator and name in PATH_FLAGS:
        return cursor + 1, _flag_cwd(name, current, inline), name == "--work-tree"
    if token in PATH_FLAGS:
        if cursor + 1 >= len(segment):
            return None
        return cursor + 2, _flag_cwd(token, current, segment[cursor + 1]), token == "--work-tree"
    if token == "-c":
        return cursor + 2, current, False
    return cursor + 1, current, False


def _git_commit_cwd(segment: list[str], cwd: Path) -> Path | None:
    segment = _unwrap_command(segment)
    if not segment or segment[0] != "git":
        return None
    current = cwd
    pinned = False
    cursor = 1
    while cursor < len(segment):
        token = segment[cursor]
        if token.startswith("-"):
            step = _skip_git_flag(segment, cursor, current)
            if step is None:
                return None
            cursor, candidate, pins = step
            if pins or not pinned:
                current = candidate
            pinned = pinned or pins
            continue
        return current if token == "commit" else None
    return None


def _strip_group_tokens(segment: list[str]) -> list[str]:
    return [token for token in segment if token not in {"(", ")"}]


def _unwrap_command(segment: list[str]) -> list[str]:
    return segment[_unwrap_start(segment):]


def _unwrap_start(segment: list[str]) -> int:
    cursor = 0
    while cursor < len(segment):
        token = segment[cursor]
        if token == "command" or _is_assignment(token):
            cursor += 1
            continue
        if token != "env":
            break
        cursor = _skip_env_prefix(segment, cursor + 1)
    return cursor


def _skip_env_prefix(segment: list[str], cursor: int) -> int:
    while cursor < len(segment):
        current = segment[cursor]
        if current in {"-i", "--ignore-environment"}:
            cursor += 1
            continue
        if current in {"-u", "--unset"}:
            cursor += 2
            continue
        if "=" in current and not current.startswith("="):
            cursor += 1
            continue
        break
    return cursor


def _is_assignment(token: str) -> bool:
    name, separator, _value = token.partition("=")
    return bool(separator and name and name.isidentifier())


def _resolve_cwd(cwd: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path


def _repo_root(cwd: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    root = result.stdout.strip()
    return Path(root) if root else None


def _staged(cwd: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _staged_text(repo: Path, path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "show", ":" + path],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
            errors="replace",
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout


if __name__ == "__main__":
    write_payload(run(read_payload()))
