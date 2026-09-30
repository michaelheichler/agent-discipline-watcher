import hashlib
import json
import re
from collections.abc import Callable, Iterable
from functools import partial
from pathlib import Path
from typing import NamedTuple

try:
    from . import catalog, principle_kb, session_state
    from .findings import Finding
except ImportError:
    import catalog
    import principle_kb
    import session_state
    from findings import Finding

MAX_MATCH_BYTES = 80
MAX_EXPLANATION_WORDS = 80
PRINCIPLE_MAP = Path(__file__).with_name("principle_map.json")
SOURCE_LABELS = {"deviq": "DevIQ", "programming-principles": "Programming Principles"}
URL_RE = re.compile(r"https?://\S+")
SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")


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


def _one_line(value: object) -> str:
    return safe_text(value).replace("\n", " ")


def _sentence(text: str) -> str:
    stripped = text.strip()
    return stripped if stripped.endswith((".", "!", "?")) else stripped + "."


class ReviewNote(NamedTuple):
    location: str
    found: str
    problem: str
    action: str


def review_row(note: ReviewNote) -> str:
    """Give model review rows one shape, because the reader acts on the same three parts from every reviewer."""
    problem, action = _sentence(_one_line(note.problem)), _sentence(_one_line(note.action))
    return f'{_one_line(note.location)} Found "{_one_line(note.found)}". Problem: {problem} Action: {action}'


def format_row(item: dict) -> str:
    """Lead with the catalog title and matched words, because a raw rule id tells the reader nothing to act on."""
    path = _one_line(item.get("path") or item.get("file") or "<pending>")
    status = _one_line(item.get("status")) if item.get("status") else ""
    prefix = f"[{status}] " if status else ""
    rule = _one_line(item.get("rule") or "")
    title = _one_line(catalog.rule_entry(rule).title)
    match = item.get("match")
    quoted = f' "{clip(_one_line(match), MAX_MATCH_BYTES)}"' if isinstance(match, str) and match.strip() else ""
    line = _one_line(item.get("line"))
    action = _one_line(item.get("action"))
    return f"{prefix}{path}:{line} {title}{quoted}. {action} ({rule})"


PrincipleLookup = Callable[[str], "principle_kb.Row | None"]
ExplainedClaim = Callable[[frozenset[str]], frozenset[str]]


class Explainer(NamedTuple):
    lookup: PrincipleLookup
    claim: ExplainedClaim
    mapping: dict[str, str]


def principle_map(path: Path = PRINCIPLE_MAP) -> dict[str, str]:
    """Read rows as data, because later rules add keys only."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {rule: entry for rule, entry in data.items() if isinstance(rule, str) and isinstance(entry, str)}


def session_explainer(config: dict | None) -> Explainer | None:
    """Skip without a session, because once needs a memory."""
    fields = config or {}
    session_id = fields.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    claim = partial(session_state.claim_explained, session_id, root=fields.get("state_root"))
    lookup = partial(principle_kb.entry, root=fields.get("principle_root"))
    return Explainer(lookup, claim, principle_map())


def _trimmed(text: str) -> str:
    """Cut at a sentence end, because half a thought misleads."""
    body = URL_RE.sub("", text)
    kept = " ".join(body.split()[:MAX_EXPLANATION_WORDS])
    ends = [match.end() for match in SENTENCE_END_RE.finditer(kept)]
    return kept[:ends[-1]] if ends else ""


def _label(row: "principle_kb.Row") -> str:
    source = SOURCE_LABELS.get(row.source, row.source)
    title = row.title.split(":")[0].strip()
    if title == title.lower():
        title = title.replace("-", " ").title()
    return f"Principle ({_one_line(source)}, {_one_line(title)}):"


def explanation(rule: str, explainer: Explainer) -> str:
    """Fail to empty, because the finding must still render."""
    entry_id = explainer.mapping.get(rule)
    if not entry_id:
        return ""
    try:
        row = explainer.lookup(entry_id)
    except Exception:
        return ""
    text = _trimmed(row.text) if row is not None else ""
    return f"{_label(row)} {_one_line(text)}" if text else ""


def explanations(rules: Iterable[str], explainer: Explainer | None) -> dict[str, str]:
    """Claim after lookup, because a failed lookup showed nothing."""
    if explainer is None:
        return {}
    found = {rule: text for rule in dict.fromkeys(rules) if (text := explanation(rule, explainer))}
    if not found:
        return {}
    try:
        claimed = explainer.claim(frozenset(found))
    except Exception:
        return {}
    return {rule: text for rule, text in found.items() if rule in claimed}


def listed_lines(listed: list[dict], explainer: Explainer | None, limit: int) -> list[str]:
    """Explain a rule once per block, because repeats cost tokens."""
    texts = explanations((str(item.get("rule") or "") for item in listed), explainer)
    lines: list[str] = []
    for number, item in enumerate(listed, 1):
        lines.append(clip(f"{number}. {format_row(item)}", limit))
        text = texts.pop(str(item.get("rule") or ""), "")
        if text:
            lines.append(clip(f"   {text}", limit))
    return lines
