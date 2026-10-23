from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from lib.baseline import split_against
from lib.commit_command import UnreadableCommit, git_calls
from lib.commit_index_source import takes_content_outside_index
from lib.config import SURFACE_COMMIT, StorageRoots, effective_config
from lib.hookio import (
    PARSE_FAILURE, advise, allow, claude_pretool_response, deny, fail_closed, read_payload, write_payload,
)
from lib.merge_state import incoming_commits, revision_text, session_started
from lib.reporting import inherited_advice, record_findings, run_with_ledger, verdict_message
from lib.scan_input import is_binary_content
from lib.scanner import file_length_findings, scan_all, scannable_text
from lib.shell_text import decode_ansi_c_value

# Suffixed .md because prose rules key off the suffix.
COMMIT_MESSAGE_PATH = "commit_message.md"
CONVENTIONAL_SUBJECT_RE = re.compile(
    r"\A(?P<prefix>[A-Za-z][A-Za-z0-9_-]*(?:\([^()\r\n]+\))?!?:[ \t]+)"
)
TRAILER_PREFIX_RE = re.compile(
    r"^(?P<prefix>(?:BREAKING CHANGE|[^\s:]+)[ \t]*:[ \t]*)"
)

COMMIT_REFUSED = "agent-discipline-watcher blocked this commit rather than letting it through. Cause: "
STAGE_SEPARATELY = (
    "The commit gate scans the index before this command runs, so it cannot judge content the same command stages "
    "or reads from the worktree. Stage in its own tool call, then commit without paths, -a, -i, -o, or -p."
)

# Named because git exits 128 when it finds no repository.
NOT_A_REPOSITORY_EXIT_CODE = 128


@dataclass(frozen=True, slots=True)
class _CommitRunContext:
    payload: dict
    config: dict | None
    roots: StorageRoots


def run(
    payload: dict,
    config: dict | None = None,
    ledger_root: str | os.PathLike[str] | None = None,
    state_root: str | os.PathLike[str] | None = None,
) -> dict:
    """Fail closed because an unreadable staged tree cannot be proven free of blocking findings."""
    context = _CommitRunContext(
        payload=payload,
        config=config,
        roots=StorageRoots(state=state_root, ledger=ledger_root),
    )
    return fail_closed("commit", lambda: _checked_run(context))


def _checked_run(context: _CommitRunContext) -> dict:
    if context.payload is PARSE_FAILURE:
        raise ValueError("unreadable hook payload")
    return _run(context)


def _run(context: _CommitRunContext) -> dict:
    return run_with_ledger(
        hook="pre_commit",
        payload=context.payload,
        gate=lambda turn_id: _index_checked_gate(context, turn_id),
        ledger_root=context.roots.ledger,
        state_root=context.roots.state,
    )


def _index_checked_gate(context: _CommitRunContext, turn_id: str) -> dict:
    try:
        calls = git_calls(_bash_command(context.payload), _payload_cwd(context.payload))
    except UnreadableCommit as exc:
        return deny(f"{COMMIT_REFUSED}{exc}")
    if takes_content_outside_index(calls):
        return deny(STAGE_SEPARATELY)
    commit_cwds = [call.cwd for call in calls if call.verb == "commit"]
    return _gate(context, turn_id, commit_cwds) if commit_cwds else allow()


def _gate(context: _CommitRunContext, turn_id: str, commit_cwds: list[Path]) -> dict:
    started = time.monotonic()
    cwd = _payload_cwd(context.payload)
    repo_rows = _repo_findings_by_repo(commit_cwds, context.config, _session_start(context))
    outer_cfg = effective_config(context.config, cwd)
    message_findings = _message_findings(_bash_command(context.payload), outer_cfg, cwd)
    stamp = _RecordStamp(
        session_id=str(context.payload.get("session_id") or ""),
        tool_use_id=str(context.payload.get("tool_use_id") or ""),
        turn_id=turn_id,
        duration_ms=int((time.monotonic() - started) * 1000),
        ledger_root=context.roots.ledger,
    )
    scan = _CommitScan(repo_rows, message_findings, outer_cfg)
    decisions = _record_all(scan, stamp)
    kind, message = verdict_message(decisions, outer_cfg) if decisions else ("release", "")
    if kind == "block":
        return deny(message)
    notice = _inherited_notice(scan)
    if kind == "observe":
        return advise("\n".join(part for part in (message, notice) if part), "PreToolUse")
    return {"systemMessage": notice} if notice else allow()


def _inherited_notice(scan: _CommitScan) -> str:
    """Report merged-in debt here, because letting it pass must not hide it."""
    notices = (inherited_advice(row.inherited, row.cfg) for row in scan.repository_rows)
    return "\n".join(notice for notice in notices if notice)


class _RecordStamp(NamedTuple):
    """Because every record_findings call in one commit shares the same turn, bundle the ledger fields once instead of repeating them."""
    session_id: str
    tool_use_id: str
    turn_id: str
    duration_ms: int
    ledger_root: str | os.PathLike[str] | None


@dataclass(frozen=True, slots=True)
class _RepoScan:
    cfg: dict
    owned: list[dict]
    inherited: list[dict]


@dataclass(frozen=True, slots=True)
class _CommitScan:
    repository_rows: list[_RepoScan]
    message_rows: list[dict]
    outer_config: dict


def _record_all(
    scan: _CommitScan, stamp: _RecordStamp
) -> list[tuple[dict, str]]:
    decisions: list[tuple[dict, str]] = []
    for row in scan.repository_rows:
        decisions.extend(record_findings(
            session_id=stamp.session_id, hook="pre_commit", event="PreCommit",
            findings=row.owned, turn_id=stamp.turn_id, tool_use_id=stamp.tool_use_id,
            duration_ms=stamp.duration_ms, root=stamp.ledger_root, config=row.cfg,
        ))
    decisions.extend(record_findings(
        session_id=stamp.session_id, hook="pre_commit", event="PreCommit",
        findings=scan.message_rows, turn_id=stamp.turn_id,
        tool_use_id=stamp.tool_use_id, duration_ms=stamp.duration_ms,
        root=stamp.ledger_root, config=scan.outer_config,
    ))
    return decisions


def _session_start(context: _CommitRunContext) -> float | None:
    session_id = str(context.payload.get("session_id") or "")
    return session_started(session_id, context.roots.state) if session_id else None


def _repo_findings_by_repo(commit_cwds: list[Path], config: dict | None, started_at: float | None) -> list[_RepoScan]:
    """Because two repos in one commit command can carry different gate configs, adjudicate each under its own, not the caller's cwd."""
    rows: list[_RepoScan] = []
    seen: set[Path] = set()
    for commit_cwd in commit_cwds:
        repo = _repo_root(commit_cwd)
        if repo is None or repo in seen:
            continue
        seen.add(repo)
        cfg = effective_config(config, repo)
        rows.append(_RepoScan(cfg, *_repo_findings(repo, cfg, started_at)))
    return rows


def _repo_findings(repo: Path, cfg: dict, started_at: float | None) -> tuple[list[dict], list[dict]]:
    """Split owned from inherited here, because a merge brings lines the agent did not write and must not own."""
    incoming = incoming_commits(repo, started_at)
    findings: list[dict] = []
    inherited: list[dict] = []
    for path in _staged(repo):
        raw = _staged_bytes(repo, path)
        if is_binary_content(path, raw):
            continue
        text = raw.decode("utf-8", errors="replace")
        scanned = file_length_findings(path, text) if scannable_text(text, cfg) is None else scan_all(path, text, cfg)
        previous = [revision_text(repo, revision, path) for revision in ("HEAD", *incoming)]
        owned, carried = split_against(previous, path, scanned, cfg, text)
        findings.extend({**finding, "path": path} for finding in owned)
        if incoming:
            inherited.extend({**finding, "path": path} for finding in carried)
    return findings, inherited


def _message_findings(command: str | list[str], cfg: dict, cwd: Path | None = None) -> list[dict]:
    """Scan the message the agent typed, because a commit's prose ships with the same authority as its code."""
    # Because git joins repeated -m values as paragraphs.
    text = "\n\n".join(_commit_messages(command, cwd))
    if not text:
        return []
    return [
        {**finding, "path": COMMIT_MESSAGE_PATH, "surface": SURFACE_COMMIT}
        for finding in scan_all(
            COMMIT_MESSAGE_PATH, text, cfg, hidden_ranges=_commit_metadata_ranges(text)
        )
    ]


def _commit_metadata_ranges(text: str) -> tuple[tuple[int, int], ...]:
    subject = CONVENTIONAL_SUBJECT_RE.match(text)
    ranges = [subject.span("prefix")] if subject else []
    ranges.extend(_trailer_metadata_ranges(text))
    return tuple(ranges)


def _trailer_metadata_ranges(text: str) -> tuple[tuple[int, int], ...]:
    lines = text.splitlines(keepends=True)
    end = len(lines) - 1
    while end >= 0 and not lines[end].strip():
        end -= 1
    start = end
    while start > 0 and lines[start - 1].strip():
        start -= 1
    if start <= 0:
        return ()
    offset = sum(len(line) for line in lines[:start])
    ranges = []
    saw_trailer = False
    for line in lines[start:end + 1]:
        match = TRAILER_PREFIX_RE.match(line)
        if match:
            ranges.append((offset + match.start("prefix"), offset + match.end("prefix")))
            saw_trailer = True
        elif not saw_trailer or not line.startswith((" ", "\t")):
            return ()
        offset += len(line)
    return tuple(ranges)


def _commit_messages(command: str | list[str], cwd: Path | None = None) -> list[str]:
    calls = git_calls(command, cwd or Path.cwd())
    return [value for call in calls if call.verb == "commit" for value in _message_values(call.args)]


def _message_value_at(tokens: list[str], cursor: int) -> tuple[str | None, int]:
    token = tokens[cursor]
    if token in {"-m", "--message"} or _is_message_bundle(token):
        next_cursor = cursor + 2
        if cursor + 1 >= len(tokens):
            return None, next_cursor
        return decode_ansi_c_value(tokens[cursor + 1]), next_cursor
    name, separator, inline = token.partition("=")
    if separator and name == "--message":
        return decode_ansi_c_value(inline), cursor + 1
    if token.startswith("-m") and len(token) > 2:
        return decode_ansi_c_value(token[2:]), cursor + 1
    return None, cursor + 1


def _message_values(tokens: list[str]) -> list[str]:
    values: list[str] = []
    cursor = 0
    while cursor < len(tokens):
        value, cursor = _message_value_at(tokens, cursor)
        if value is not None:
            values.append(value)
    return values


_BOOLEAN_BUNDLE_CHARS = frozenset("anqvoe")


def _is_message_bundle(token: str) -> bool:
    if not token.startswith("-") or token.startswith("--") or len(token) <= 2:
        return False
    if token[-1] != "m":
        return False
    return all(char in _BOOLEAN_BUNDLE_CHARS for char in token[1:-1])


def _bash_command(payload: dict) -> str | list[str]:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    for key in ("command", "cmd", "input"):
        if key in tool_input:
            command = tool_input[key]
            return list(command) if isinstance(command, list) else str(command)
    return ""


def _payload_cwd(payload: dict) -> Path:
    return Path(payload.get("cwd") or os.getcwd())


# Because a bad revision also exits 128.
NOT_A_GIT_REPOSITORY_MESSAGE = "not a git repository"


def _run_git(args: list[str], cwd: Path, errors: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, text=True, capture_output=True, check=True, timeout=30, errors=errors,
        )
    except subprocess.CalledProcessError as exc:
        if exc.returncode == NOT_A_REPOSITORY_EXIT_CODE and NOT_A_GIT_REPOSITORY_MESSAGE in (exc.stderr or "").lower():
            return None
        raise


def _repo_root(cwd: Path) -> Path | None:
    result = _run_git(["rev-parse", "--show-toplevel"], cwd, "strict")
    if result is None:
        return None
    root = result.stdout.strip()
    return Path(root) if root else None


def _staged(cwd: Path) -> list[str]:
    result = _run_git(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"], cwd, "strict")
    if result is None:
        return []
    return [path for path in result.stdout.split("\0") if path]


def _staged_bytes(repo: Path, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", ":" + path], cwd=repo,
        capture_output=True, check=True, timeout=30,
    )
    return result.stdout


if __name__ == "__main__":
    write_payload(claude_pretool_response(run(read_payload())))
