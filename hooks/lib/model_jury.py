from __future__ import annotations

import contextlib
import importlib
import importlib.util
import os
import re
import sys
from pathlib import Path

try:
    from .ledger import touched_files
    from .scanner import _is_exempt, _is_prose
except ImportError:
    from ledger import touched_files
    from scanner import _is_exempt, _is_prose


SKILLS_ROOT = Path(__file__).resolve().parents[3]
OLD_ENGLISH_LIB = SKILLS_ROOT / "english-for-agents" / "hooks" / "lib"
OLD_CLEAN_LIB = SKILLS_ROOT / "clean-coder-discipline" / "hooks" / "lib"
CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".go", ".rs",
    ".rb", ".php", ".cs", ".c", ".h", ".cc", ".cpp", ".hpp", ".swift", ".kt",
    ".kts", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".sql", ".lua", ".vim",
    ".yaml", ".yml", ".toml", ".json",
}


def judge_touched(payload: dict, config: dict) -> list[dict]:
    findings: list[dict] = []
    attempted_english = False
    attempted_clean = False
    try:
        for path in touched_files(config):
            if _is_exempt(path, config):
                continue
            full = Path(path)
            if not full.is_file():
                continue
            text = full.read_text(encoding="utf-8", errors="replace")
            if config.get("english") and _is_prose(str(full)):
                attempted_english = True
                findings.extend(_english_findings(str(full), text, config))
            if config.get("clean_code") and _is_code(str(full)):
                attempted_clean = True
                findings.extend(_clean_findings(str(full), text, config))
    finally:
        _release_host_turn(str(payload.get("session_id") or config.get("session_id") or "default"), config)
        _unload_english(config, attempted_english)
        _unload_clean(config, attempted_clean)
    return findings


def _english_findings(path: str, text: str, config: dict) -> list[dict]:
    try:
        pipeline = config.get("_english_pipeline") or _import_old("pipeline", OLD_ENGLISH_LIB)
        gate = config.get("_english_model_gate") or _old_gate(OLD_ENGLISH_LIB / "ledger.py", "adw_english_ledger")
        with gate() as has_room:
            if not has_room:
                return []
            split = getattr(pipeline, "_split_sentences", None)
            sentences = split(text) if callable(split) else _split_sentences(text)
            raw = pipeline.scan_sentences_graded(sentences)
    except Exception as exc:
        _warn(f"agent-discipline-watcher: English model jury skipped {path}: {exc}")
        return []
    return [_english_row(path, text, item) for item in raw if isinstance(item, dict)]


def _clean_findings(path: str, text: str, config: dict) -> list[dict]:
    try:
        deep_judge = config.get("_clean_deep_judge") or _import_old("deep_judge", OLD_CLEAN_LIB)
        gate = config.get("_clean_model_gate") or _old_gate(OLD_CLEAN_LIB / "ledger.py", "adw_clean_ledger")
        with gate() as has_room:
            if not has_room:
                return []
            raw = deep_judge.scan_code(path, text)
    except Exception as exc:
        _warn(f"agent-discipline-watcher: Clean Coder model jury skipped {path}: {exc}")
        return []
    return [_clean_row(path, item) for item in raw if isinstance(item, dict)]


def _english_row(path: str, text: str, item: dict) -> dict:
    sentence = _text(item.get("sentence") or item.get("snippet"))
    line = _line_for(text, sentence, item.get("offset"))
    fix = _text(item.get("fix") or item.get("detail"))
    source = _text(item.get("source"))
    detail = fix + (f" [{source}]" if source else "")
    return _finding(
        path,
        "english",
        _short_rule(item.get("cat") or item.get("rule"), "model_prose"),
        line,
        detail or "Model-backed prose jury finding.",
        False,
        sentence,
        fix or "Rewrite the sentence plainly.",
    )


def _clean_row(path: str, item: dict) -> dict:
    detail = _text(item.get("detail")) or "Model-backed clean-code jury finding."
    return _finding(
        path,
        "clean_code",
        _short_rule(item.get("rule"), "deep_clean_code"),
        int(item.get("line") or 1),
        detail,
        bool(item.get("force")),
        _text(item.get("snippet")),
        _text(item.get("next_code")) or detail or "Simplify the code.",
    )


def _finding(path: str, family: str, rule: str, line: int, detail: str, force: bool, snippet: str, action: str) -> dict:
    return {
        "path": path,
        "family": family,
        "rule": rule,
        "line": line or 1,
        "detail": detail,
        "force": force,
        "snippet": snippet.strip()[:180],
        "action": action,
    }


def _old_gate(path: Path, name: str):
    ledger = _load_source_module(name, path)
    return ledger.model_load_gate


def _import_old(name: str, directory: Path):
    existing = sys.modules.get(name)
    if existing is not None and _module_from(existing, directory):
        return existing
    with _path_front(directory):
        if existing is not None:
            sys.modules.pop(name, None)
        try:
            return importlib.import_module(name)
        except Exception:
            if existing is not None:
                sys.modules[name] = existing
            raise


def _load_source_module(name: str, path: Path):
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _module_from(module, directory: Path) -> bool:
    raw = getattr(module, "__file__", "")
    if not raw:
        return False
    try:
        return Path(raw).resolve().is_relative_to(directory.resolve())
    except OSError:
        return False


@contextlib.contextmanager
def _path_front(directory: Path):
    raw = str(directory)
    inserted = raw not in sys.path
    if inserted:
        sys.path.insert(0, raw)
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(raw)
            except ValueError:
                pass


def _unload_english(config: dict, attempted: bool) -> None:
    if not attempted:
        return
    pipeline = config.get("_english_pipeline") or sys.modules.get("pipeline")
    _call_unload(pipeline)
    _call_unload(sys.modules.get("arbiter"))


def _unload_clean(config: dict, attempted: bool) -> None:
    if not attempted:
        return
    _call_unload(config.get("_clean_deep_judge") or sys.modules.get("deep_judge"))


def _call_unload(module) -> None:
    unload = getattr(module, "unload", None)
    if callable(unload):
        try:
            unload()
        except Exception:
            pass


def _release_host_turn(turn_id: str, config: dict) -> None:
    try:
        host_client = config.get("_host_client")
        if host_client is None:
            sml = os.environ.get("SML_DIR") or str(SKILLS_ROOT / "skill-model-loader")
            if os.path.isdir(sml) and sml not in sys.path:
                sys.path.insert(0, sml)
            host_client = importlib.import_module("host_client")
        host_client.release_turn(turn_id)
    except Exception:
        pass


def _line_for(text: str, snippet: str, offset) -> int:
    if isinstance(offset, int) and offset >= 0:
        return text.count("\n", 0, offset) + 1
    needle = snippet.strip()
    found = text.find(needle) if needle else -1
    return text.count("\n", 0, found) + 1 if found >= 0 else 1


def _short_rule(value, default: str) -> str:
    text = _text(value).strip().lower()
    if not text or len(text) > 48:
        return default
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or default


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if len(part.split()) >= 4]


def _is_code(path: str) -> bool:
    return Path(path).suffix.lower() in CODE_EXTS


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _warn(message: str) -> None:
    try:
        print(message, file=sys.stderr)
    except Exception:
        pass
