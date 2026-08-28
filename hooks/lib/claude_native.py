"""Generate and manage ADW's native Claude model-review hook block."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


PRESETS = ("mixed", "luna", "haiku", "sonnet")
REMOTE_ENV = "CLAUDE_CODE_REMOTE"
HAIKU_ONLY_ENV = "ADW_CLAUDE_HAIKU_ONLY"
PRESET_ENV = "ADW_CLAUDE_PRESET"
SETTINGS_ENV = "ADW_CLAUDE_SETTINGS"
PRESET_FILE_ENV = "ADW_CLAUDE_PRESET_FILE"
MANAGED_MARKER = "adw-managed-hook-v1"
WRITE_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|apply_patch|Bash"
MAX_FAILURE_MESSAGE = 256


def _validate_preset(value: str) -> str:
    if value not in PRESETS:
        raise ValueError("preset must be exactly mixed, luna, haiku, or sonnet")
    return value


def preset_path(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    return Path(env.get(PRESET_FILE_ENV, str(Path.home() / ".adw" / "claude" / "preset"))).expanduser()


def settings_path(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    return Path(env.get(SETTINGS_ENV, str(Path.home() / ".claude" / "settings.json"))).expanduser()


def read_preset(path: str | Path | None = None) -> str | None:
    target = Path(path) if path is not None else preset_path()
    try:
        value = target.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return value if value in PRESETS else None


def default_preset(
    environment: Mapping[str, str] | None = None,
    *,
    preset_path: str | Path | None = None,
) -> str:
    env = os.environ if environment is None else environment
    explicit = env.get(PRESET_ENV, "").strip()
    if explicit:
        return _validate_preset(explicit)
    haiku_only = env.get(HAIKU_ONLY_ENV, "").strip().lower()
    if haiku_only in {"1", "true", "yes"}:
        return "haiku"
    stored = read_preset(preset_path)
    if stored is not None:
        return stored
    return "haiku" if env.get(REMOTE_ENV) == "true" else "mixed"


def _model_for(preset: str, role: str) -> str:
    if preset == "mixed":
        return "haiku" if role == "comment" else "sonnet"
    if preset == "haiku":
        return "haiku"
    if preset == "sonnet":
        return "sonnet"
    return "luna"


def comment_prompt(preset: str) -> str:
    _validate_preset(preset)
    route = (
        "Use ADW's Luna subscription route and do not invoke a Claude fallback."
        if preset == "luna" else "Use only the selected native Claude model."
    )
    return (
        f"{MANAGED_MARKER}\n"
        "You are ADW's post-write comment verifier.\n"
        "Inspect only the just-written candidate file and the bounded candidate data in the hook input. "
        "Use read-only inspection. Do not edit files, settings, or unrelated paths.\n"
        f"{route}\n"
        "Parse the hook input supplied after this prompt. If it is empty, malformed, unrelated to a write, "
        "or has no ADW candidate, return exactly {\"ok\": true}.\n"
        "A successful check returns exactly {\"ok\": true}. A failed check returns {\"ok\": false, "
        "\"reason\": \"one bounded remediation instruction\"}.\n"
        "Do not deny or undo the completed write."
    )


def stop_prompt(preset: str) -> str:
    _validate_preset(preset)
    route = (
        "Use ADW's Luna subscription route and do not invoke a Claude fallback."
        if preset == "luna" else "Use only the selected native Claude model."
    )
    return (
        f"{MANAGED_MARKER}\n"
        "You are ADW's Stop verifier.\n"
        "Check stop_hook_active before doing any work. If it is true, return exactly {\"ok\": true}. "
        "Read only the current session's bounded ADW candidate journal and the files named by those candidates. "
        "Use read-only inspection. Do not scan unrelated files or edit files or settings.\n"
        f"{route}\n"
        "Batch all current prose and document candidates in one review. Empty or malformed ADW-owned input "
        "returns exactly {\"ok\": true}. A clean review returns exactly {\"ok\": true}. A failed review "
        "returns {\"ok\": false, \"reason\": \"one bounded remediation instruction\"}."
    )


def generated_hooks(preset: str) -> dict[str, list[dict[str, Any]]]:
    selected = _validate_preset(preset)
    return {
        "PostToolUse": [{
            "matcher": WRITE_MATCHER,
            "hooks": [{
                "type": "agent",
                "model": _model_for(selected, "comment"),
                "timeout": 120,
                "prompt": comment_prompt(selected),
            }],
        }],
        "Stop": [{
            "hooks": [{
                "type": "agent",
                "model": _model_for(selected, "document"),
                "timeout": 120,
                "prompt": stop_prompt(selected),
            }],
        }],
    }


def _is_managed_hook(value: object) -> bool:
    return isinstance(value, dict) and value.get("type") == "agent" and MANAGED_MARKER in str(value.get("prompt", ""))


def _without_managed(settings: dict[str, Any]) -> dict[str, Any]:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings
    cleaned: dict[str, Any] = dict(settings)
    cleaned_hooks: dict[str, Any] = dict(hooks)
    for lifecycle, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        next_groups: list[Any] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                next_groups.append(group)
                continue
            remaining = [hook for hook in group["hooks"] if not _is_managed_hook(hook)]
            if len(remaining) == len(group["hooks"]):
                next_groups.append(group)
            elif remaining:
                next_groups.append({**group, "hooks": remaining})
        if next_groups:
            cleaned_hooks[lifecycle] = next_groups
        else:
            cleaned_hooks.pop(lifecycle, None)
    cleaned["hooks"] = cleaned_hooks
    return cleaned


def settings_for_preset(settings: object, preset: str) -> dict[str, Any]:
    if not isinstance(settings, dict):
        raise ValueError("Claude settings must be a JSON object")
    selected = _validate_preset(preset)
    merged = _without_managed(dict(settings))
    hooks = dict(merged.get("hooks")) if isinstance(merged.get("hooks"), dict) else {}
    for lifecycle, groups in generated_hooks(selected).items():
        existing = hooks.get(lifecycle)
        hooks[lifecycle] = list(existing) if isinstance(existing, list) else []
        hooks[lifecycle].extend(groups)
    merged["hooks"] = hooks
    return merged


def _load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read Claude settings: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Claude settings must be a JSON object")
    return value


def _atomic_write(path: Path, text: str) -> None:
    target = path.resolve() if path.is_symlink() else path
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
        temporary.chmod(mode)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def set_preset(
    preset: str,
    *,
    settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> str:
    selected = _validate_preset(preset)
    target_settings = Path(settings_path).expanduser() if settings_path is not None else globals()["settings_path"]()
    target_preset = Path(preset_path).expanduser() if preset_path is not None else globals()["preset_path"]()
    current = _load_settings(target_settings)
    rendered = json.dumps(settings_for_preset(current, selected), indent=2, sort_keys=True) + "\n"
    _atomic_write(target_settings, rendered)
    _atomic_write(target_preset, selected + "\n")
    return selected


def status(*, settings_path: str | Path | None = None, preset_path: str | Path | None = None, environment: Mapping[str, str] | None = None) -> dict[str, str]:
    selected = read_preset(preset_path) or default_preset(environment, preset_path=preset_path)
    return {"preset": selected, "settings": str(settings_path or globals()["settings_path"]()), "watch": "settings-only changes are watched automatically; reload plugins after plugin install or source updates"}


def fallback_after_luna_failure(
    role: str,
    reason: str,
    *,
    settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> dict[str, Any]:
    if role not in {"comment", "prose", "document"}:
        raise ValueError("role must be comment, prose, or document")
    current = read_preset(preset_path) or "mixed"
    fallback = "haiku" if role == "comment" else "sonnet"
    if current == "luna":
        set_preset(fallback, settings_path=settings_path, preset_path=preset_path)
        switched = True
    else:
        fallback = current
        switched = False
    bounded = " ".join(str(reason).split())[:MAX_FAILURE_MESSAGE]
    return {
        "preset": fallback,
        "switched": switched,
        "message": f"Luna {role} review unavailable: {bounded}. Switched subsequent events to {fallback}.",
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="adw-judge")
    parser.add_argument("preset", choices=(*PRESETS, "status"))
    args = parser.parse_args(argv)
    try:
        if args.preset == "status":
            print(json.dumps(status(), sort_keys=True))
        else:
            selected = set_preset(args.preset)
            print(f"ADW Claude preset: {selected}. Settings-only changes are watched automatically; /reload-plugins is for plugin install or source updates.")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"adw-judge: {exc}\n")
    return 0
