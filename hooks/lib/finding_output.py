import hashlib
import json
import re
from pathlib import Path

try:
    from .findings import Finding
except ImportError:
    from findings import Finding


def safe_component(value: object, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "")).strip("._")[:48]
    return text or fallback


def canonical_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        return str(Path(value).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return value


def finding_content_hash(finding: dict) -> str:
    value = finding.get("content_hash")
    if isinstance(value, str) and value:
        return value
    identity = {key: finding.get(key) for key in ("detail", "snippet", "action", "line")}
    encoded = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def deduplicated(findings: list[dict], config: dict | None = None) -> list[dict]:
    cfg = config or {}
    seen: set[tuple[object, ...]] = set()
    result: list[dict] = []
    for raw_finding in findings:
        finding = raw_finding.to_dict() if isinstance(raw_finding, Finding) else raw_finding
        if not isinstance(finding, dict):
            continue
        key = (
            cfg.get("session_id", ""), cfg.get("turn_id", ""), finding.get("rule"),
            canonical_path(finding.get("path") or finding.get("file")),
            finding_content_hash(finding), finding.get("line"), finding.get("snippet"),
        )
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result


def safe_text(value: object) -> str:
    safe: list[str] = []
    for character in str(value):
        code = ord(character)
        if character == "\n":
            safe.append(character)
        elif code < 32 or code == 127 or 0x80 <= code <= 0x9F or 0x202A <= code <= 0x202E or 0x2066 <= code <= 0x2069:
            safe.append(" ")
        else:
            safe.append({"`": "'", "<": "‹", ">": "›"}.get(character, character))
    return "".join(safe)


def clip(value: object, limit: int) -> str:
    text = safe_text(value)
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:max(limit - 3, 0)].decode("utf-8", errors="ignore") + "..."


def format_row(item: dict) -> str:
    path = safe_text(item.get("path") or item.get("file") or "<pending>").replace("\n", " ")
    status = safe_text(item.get("status")).replace("\n", " ") if item.get("status") else ""
    prefix = f"[{status}] " if status else ""
    family = safe_text(item.get("family")).replace("\n", " ")
    rule = safe_text(item.get("rule")).replace("\n", " ")
    line = safe_text(item.get("line")).replace("\n", " ")
    action = safe_text(item.get("action")).replace("\n", " ")
    return f"{prefix}{path}:{line} {family}/{rule}: {action}"
