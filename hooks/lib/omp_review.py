from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import payloads
from .config import effective_hook_config
from .journal import _read_regular_content
from .narration_candidates import COMMENTABLE_EXTS
from .omp_review_findings import validated_findings
from .omp_review_requests import build_work, wire_request
from .scanner import PROSE_EXTS

REVIEW_SUFFIXES = COMMENTABLE_EXTS | PROSE_EXTS | {".py"}


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


def run(request: object, config: dict | None = None) -> dict:
    if not isinstance(request, dict) or not isinstance(request.get("payload"), dict):
        raise ValueError("invalid OMP review bridge request")
    operation, payload = request.get("operation"), request["payload"]
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
