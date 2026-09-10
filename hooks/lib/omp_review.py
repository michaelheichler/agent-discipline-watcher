from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pre_bash
from . import payloads
from .config import effective_hook_config
from .journal import _read_regular_content
from .narration_candidates import COMMENTABLE_EXTS
from .omp_review_findings import validated_findings
from .omp_review_requests import build_work, wire_request
from .scanner import PROSE_EXTS

REVIEW_SUFFIXES = COMMENTABLE_EXTS | PROSE_EXTS | {".py"}
MAX_TARGET_PATHS = 32
MAX_TARGET_BYTES = 64 * 1024
MAX_TARGET_DEPTH = 2


def read_source(path: Path) -> str:
    outcome = _read_regular_content(path)
    if outcome.status != "available" or outcome.value is None:
        raise ValueError(f"could not read a stable UTF-8 source file within 128 KiB: {path}")
    return outcome.value[1]


def _target(payload: dict) -> Path:
    raw, cwd = payloads.file_path(payload), payloads.cwd(payload)
    if not raw or not cwd:
        raise ValueError("OMP review needs a source path and session directory")
    target = Path(raw).expanduser()
    return (target if target.is_absolute() else Path(cwd) / target).resolve()


def _digest(path: Path, source: str, config: dict) -> str:
    data = json.dumps([str(path), source, config], sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _bash_changes_directory(command: str) -> bool:
    for segment in pre_bash._segments(command):
        index = pre_bash._command_word_index(segment)
        words = [pre_bash._basename(token) for token in segment[index:]]
        if words and words[0] in {"cd", "pushd", "popd"}:
            return True
        if len(words) > 1 and words[0] in {"command", "builtin"} and words[1] in {"cd", "pushd", "popd"}:
            return True
        for position, token in enumerate(segment[:index]):
            wrapper = pre_bash._basename(token)
            if wrapper not in {"env", "sudo"}:
                continue
            change_flag = "-C" if wrapper == "env" else "-D"
            if any(
                option == change_flag
                or option.startswith(change_flag)
                or option == "--chdir"
                or option.startswith("--chdir=")
                for option in segment[position + 1:index]
            ):
                return True
    return False


def _bash_target_paths(payload: dict) -> list[str]:
    fields = payloads.exact_string_dict(payload)
    tool_input = payloads._tool_input_from(fields)
    command = tool_input.get("command")
    if not isinstance(command, str) or len(command.encode("utf-8")) > MAX_TARGET_BYTES:
        raise ValueError("OMP target bridge needs a bounded Bash command")
    paths: list[str] = list(payloads.edited_paths(payload))
    queue: list[tuple[str, int]] = [(command, 0)]
    seen: set[str] = set()
    aggregate_bytes = len(command.encode("utf-8"))
    directory_changed = _bash_changes_directory(command)
    extractors = (
        pre_bash._literal_shell_c_payloads,
        pre_bash._literal_shell_stdin_payloads,
        pre_bash._literal_shell_pipe_payloads,
    )
    while queue:
        source, depth = queue.pop(0)
        if source in seen:
            continue
        seen.add(source)
        directory_changed = directory_changed or _bash_changes_directory(source)
        if depth > 0:
            paths.extend(pre_bash.write_paths(source))
            if len(paths) > MAX_TARGET_PATHS:
                raise ValueError("OMP target bridge returned too many Bash targets")
        nested: list[str] = []
        for extractor in extractors:
            nested.extend(extractor(source))
        if nested and depth >= MAX_TARGET_DEPTH:
            raise ValueError("OMP target bridge cannot prove a nested Bash write")
        for child in nested:
            aggregate_bytes += len(child.encode("utf-8"))
            if aggregate_bytes > MAX_TARGET_BYTES:
                raise ValueError("OMP target bridge nested Bash input exceeds its size limit")
            queue.append((child, depth + 1))
    if any(path.startswith("~") and path != "~" and not path.startswith("~/") for path in paths):
        raise ValueError("OMP target bridge cannot resolve named home paths. Use an absolute path.")
    if directory_changed and any(
        not Path(path).is_absolute() and not path.startswith("~") for path in paths
    ):
        raise ValueError("Bash write targets after a working-directory change must be absolute paths")
    return list(dict.fromkeys(paths))


def run(request: object, config: dict | None = None) -> dict:
    if not isinstance(request, dict) or not isinstance(request.get("payload"), dict):
        raise ValueError("invalid OMP review bridge request")
    operation, payload = request.get("operation"), request["payload"]
    if operation == "targets":
        if payloads.tool_name(payload).lower() != "bash":
            raise ValueError("OMP target bridge only supports Bash calls")
        paths = _bash_target_paths(payload)
        if len(paths) > MAX_TARGET_PATHS or any(
            not isinstance(path, str) or not path or len(path) > 4096 or any(char in path for char in "\"'\\")
            for path in paths
        ):
            raise ValueError("OMP target bridge returned invalid paths")
        return {"paths": list(dict.fromkeys(paths))}
    if operation not in {"prepare", "validate"}:
        raise ValueError("unknown OMP review bridge operation")
    cfg = effective_hook_config(config, payloads.cwd(payload) or None)
    boundary = cfg.get("data_boundary")
    if not isinstance(boundary, dict) or boundary.get("enabled") is not True:
        return {"enabled": False, "requests": []}
    target = _target(payload)
    if target.suffix.lower() not in REVIEW_SUFFIXES:
        return {"enabled": True, "requests": []}
    source = read_source(target)
    digest = _digest(target, source, cfg)
    work = build_work(target, source, cfg)
    if operation == "prepare":
        return {
            "enabled": True, "model": str(cfg.get("adw_model") or ""),
            "path": str(target), "digest": digest,
            "requests": [wire_request(index, item) for index, item in enumerate(work)],
        }
    if request.get("digest") != digest:
        raise ValueError("source or review policy changed during OMP review; retry the file")
    index = request.get("request_id")
    if type(index) is not int or not 0 <= index < len(work):
        raise ValueError("invalid OMP review request index")
    return validated_findings(work[index], request.get("output"), {**cfg, "session_id": payloads.session_id(payload)})
