"""Narrow Haiku adjudication for lexical WHAT-comment edge cases."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path

try:
    from . import session_state
except ImportError:
    import session_state


DEFAULT_MODEL = "claude-haiku-4-5-20251001"
TIMEOUT_SECONDS = 3.0
PROMPT = """Classify the final code comment or docstring as WHAT or WHY.
WHAT restates behavior visible from the code. WHY explains a constraint, tradeoff, failure mode, or non-obvious reason.

Comment: Returns the cached item.
Label: WHAT

Comment: Keep the cache because callers rely on stable object identity.
Label: WHY

Comment: 5ms budget
Label: WHY

Comment: Scans entries because malformed files must not abort cleanup.
Label: WHY

Comment: {text}
Label:"""


def _settings(config: dict) -> dict:
    value = config.get("escalation")
    return value if isinstance(value, dict) else {}


def _cache_path(text: str, config: dict) -> Path:
    root = config.get("state_root")
    base = Path(root) if root is not None else session_state._default_root()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return base / "escalation" / f"{digest}.json"


def _cached_verdict(path: Path) -> bool | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    verdict = data.get("verdict") if isinstance(data, dict) else None
    return verdict == "what" if verdict in ("what", "why") else None


def _store_verdict(path: Path, verdict: bool, model: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".escalation.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"verdict": "what" if verdict else "why", "model": model}, handle)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _sdk_label(api_key: str, model: str, prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=0)
    response = client.messages.create(
        model=model,
        max_tokens=4,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = getattr(response, "content", [])
    return "".join(getattr(part, "text", "") for part in parts)


def _http_label(api_key: str, model: str, prompt: str) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 4,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        data = json.loads(response.read().decode("utf-8"))
    return "".join(part.get("text", "") for part in data.get("content", []) if isinstance(part, dict))


def _remote_verdict(text: str, model: str) -> bool | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    prompt = PROMPT.format(text=text)
    try:
        try:
            label = _sdk_label(api_key, model, prompt)
        except ImportError:
            label = _http_label(api_key, model, prompt)
    except Exception:  # noqa: BLE001 (an API failure must fall back to the heuristic, never fail the hook)
        return None
    normalized = label.strip().upper()
    if normalized.startswith("WHAT"):
        return True
    if normalized.startswith("WHY"):
        return False
    return None


def _consume_api_slot(config: dict) -> bool:
    remaining = config.get("_escalation_remaining")
    if not isinstance(remaining, int):
        return True
    if remaining <= 0:
        return False
    config["_escalation_remaining"] = remaining - 1
    return True


def classify_what(text: str, heuristic_verdict: bool, config: dict) -> bool:
    """Use a cached Haiku verdict when enabled, otherwise preserve the heuristic decision."""
    settings = _settings(config)
    if settings.get("enabled") is not True:
        return heuristic_verdict
    model = settings.get("model")
    if not isinstance(model, str) or not model:
        model = DEFAULT_MODEL
    try:
        path = _cache_path(text, config)
        cached = _cached_verdict(path)
        if cached is not None:
            return cached
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return heuristic_verdict
        if not _consume_api_slot(config):
            return heuristic_verdict
        verdict = _remote_verdict(text, model)
        if verdict is None:
            return heuristic_verdict
        _store_verdict(path, verdict, model)
        return verdict
    except Exception:  # noqa: BLE001 (cache or network trouble must not turn into a deny)
        return heuristic_verdict
