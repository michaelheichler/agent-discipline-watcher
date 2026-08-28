"""Generate and manage ADW's native Claude model-review hook block."""
from __future__ import annotations

import json
from contextlib import contextmanager
import fcntl
import hashlib
import os
import shlex
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterator, Mapping


PRESETS = ("mixed", "luna", "haiku", "sonnet")
REMOTE_ENV = "CLAUDE_CODE_REMOTE"
HAIKU_ONLY_ENV = "ADW_CLAUDE_HAIKU_ONLY"
PRESET_ENV = "ADW_CLAUDE_PRESET"
SETTINGS_ENV = "ADW_CLAUDE_SETTINGS"
PRESET_FILE_ENV = "ADW_CLAUDE_PRESET_FILE"
MANAGED_MARKER = "adw-managed-hook-v1"
TRANSACTION_SUFFIX = ".txn"
LOCK_SUFFIX = ".lock"
TRANSACTION_VERSION = 2
WRITE_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|apply_patch|Bash"
MAX_FAILURE_MESSAGE = 256
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
LUNA_HANDLER_PATH = PLUGIN_ROOT / "hooks" / "claude_luna.sh"
JOURNAL_READER_PATH = shlex.quote(str(PLUGIN_ROOT / "hooks" / "read_claude_journal.sh"))


class LunaUnavailable(RuntimeError):
    """Provider failure that allows the managed native fallback to take over."""


def _validate_preset(value: str) -> str:
    if value not in PRESETS:
        raise ValueError("preset must be exactly mixed, luna, haiku, or sonnet")
    return value


def parse_decision(value: object) -> dict[str, Any]:
    """Keep malformed native output from becoming a deterministic gate decision."""
    if type(value) is not dict or type(value.get("ok")) is not bool:
        return {"ok": True}
    expected = {"ok"} if value["ok"] is True else {"ok", "reason"}
    if set(value) != expected:
        return {"ok": True}
    if value["ok"] is True:
        return {"ok": True}
    reason = value.get("reason")
    if type(reason) is not str or not reason.strip():
        return {"ok": True}
    return {"ok": False, "reason": " ".join(reason.split())[:MAX_FAILURE_MESSAGE]}


def preset_path(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    return Path(env.get(PRESET_FILE_ENV, str(Path.home() / ".adw" / "claude" / "preset"))).expanduser()


def settings_path(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    return Path(env.get(SETTINGS_ENV, str(Path.home() / ".claude" / "settings.json"))).expanduser()


def _canonical(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _transaction_path(path: str | Path) -> Path:
    target = _canonical(path)
    return target.with_name(target.name + TRANSACTION_SUFFIX)


def _lock_path(path: str | Path) -> Path:
    target = _canonical(path)
    return target.with_name(target.name + LOCK_SUFFIX)


@contextmanager
def _preset_lock(path: str | Path) -> Iterator[None]:
    lock = _lock_path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"preset lock is not a regular file: {lock}")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _read_preset_unlocked(path: Path) -> str | None:
    try:
        text = _read_regular_text(path)
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if text is None:
        return None
    value = text.strip()
    return value if value in PRESETS else None


def _read_regular_text(path: Path) -> str | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError(f"preset state leaf is not safely readable: {path}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"preset state leaf is not a regular file: {path}")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            return handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _discard_transaction(path: Path) -> None:
    # unlink never follows a final symlink, which also quarantines a crafted txn leaf without touching its target.
    try:
        _transaction_path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _transaction_payload(path: Path) -> dict[str, Any] | None:
    transaction = _transaction_path(path)
    text = _read_regular_text(transaction)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read preset transaction: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("preset transaction must be a JSON object")
    expected = {"version", "preset", "base_preset", "base_settings_hash"}
    if set(payload) != expected or payload.get("version") != TRANSACTION_VERSION or payload.get("preset") not in PRESETS:
        raise ValueError("invalid preset transaction")
    if payload["base_preset"] is not None and payload["base_preset"] not in PRESETS:
        raise ValueError("invalid base preset in transaction")
    base_hash = payload["base_settings_hash"]
    if base_hash is not None and (
        not isinstance(base_hash, str) or len(base_hash) != 64
        or any(character not in "0123456789abcdef" for character in base_hash)
    ):
        raise ValueError("invalid base settings hash in transaction")
    return payload


def _settings_snapshot(path: Path) -> tuple[str | None, dict[str, Any]]:
    text = _read_regular_text(path)
    if text is None:
        return None, {}
    try:
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read Claude settings: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Claude settings must be a JSON object")
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), value


def _recover_unlocked(settings: Path, preset: Path) -> None:
    try:
        payload = _transaction_payload(preset)
    except (OSError, ValueError):
        _discard_transaction(preset)
        return
    if payload is None:
        return
    desired = str(payload["preset"])
    base_preset = payload["base_preset"]
    current_preset = _read_preset_unlocked(preset)
    if current_preset not in {base_preset, desired}:
        _discard_transaction(preset)
        return
    if current_preset is None and preset.exists():
        _discard_transaction(preset)
        return
    current_hash, current_settings = _settings_snapshot(settings)
    # The hash distinguishes a crash window from a later external edit. Both paths merge the managed block onto the
    # latest valid settings object, so a stale transaction cannot replay an old complete settings snapshot.
    _ = current_hash == payload["base_settings_hash"]
    rendered = json.dumps(settings_for_preset(current_settings, desired), indent=2, sort_keys=True) + "\n"
    _atomic_write(settings, rendered)
    _atomic_write(preset, desired + "\n")
    _discard_transaction(preset)


def _recover(
    *,
    settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> None:
    target_preset = _canonical(preset_path) if preset_path is not None else _canonical(globals()["preset_path"]())
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)


def recover(*, settings_path: str | Path | None = None, preset_path: str | Path | None = None) -> None:
    """Complete a durable preset transition left by an interrupted writer."""
    _recover(settings_path=settings_path, preset_path=preset_path)


def read_preset(
    path: str | Path | None = None,
    *,
    settings_path: str | Path | None = None,
) -> str | None:
    target = _canonical(path) if path is not None else _canonical(globals()["preset_path"]())
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    with _preset_lock(target):
        try:
            _recover_unlocked(target_settings, target)
        except (OSError, ValueError):
            return None
        return _read_preset_unlocked(target)


def _default_preset_unlocked(env: Mapping[str, str], target_preset: Path) -> str:
    explicit = env.get(PRESET_ENV, "").strip()
    if explicit:
        return _validate_preset(explicit)
    haiku_only = env.get(HAIKU_ONLY_ENV, "").strip().lower()
    if haiku_only in {"1", "true", "yes"}:
        return "haiku"
    stored = _read_preset_unlocked(target_preset)
    if stored is not None:
        return stored
    return "haiku" if env.get(REMOTE_ENV) == "true" else "mixed"


def default_preset(
    environment: Mapping[str, str] | None = None,
    *,
    preset_path: str | Path | None = None,
    settings_path: str | Path | None = None,
) -> str:
    env = os.environ if environment is None else environment
    target_preset = _canonical(preset_path) if preset_path is not None else _canonical(globals()["preset_path"]())
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    with _preset_lock(target_preset):
        try:
            _recover_unlocked(target_settings, target_preset)
        except (OSError, ValueError):
            pass
        return _default_preset_unlocked(env, target_preset)


def _model_for(preset: str, role: str) -> str:
    if preset == "mixed":
        return "haiku" if role == "comment" else "sonnet"
    if preset == "haiku":
        return "haiku"
    if preset == "sonnet":
        return "sonnet"
    raise ValueError("luna uses command handlers, not a native model")


def _luna_command() -> str:
    return f"ADW_CLAUDE_MANAGED={MANAGED_MARKER} {shlex.quote(str(LUNA_HANDLER_PATH))}"


def comment_prompt(preset: str) -> str:
    _validate_preset(preset)
    return (
        f"{MANAGED_MARKER}\n"
        "You are ADW's post-write comment verifier.\n"
        "Matching hooks run in parallel. Inspect only the just-written eligible file named by this raw host event; "
        "do not expect another hook to have prepared context and do not duplicate the raw event content. "
        "Use read-only inspection. Do not edit files, settings, or unrelated paths.\n"
        "Parse the hook input supplied after this prompt. If it is empty, malformed, unrelated to a write, "
        "or has no ADW candidate, return exactly {\"ok\": true}.\n"
        "A successful check returns exactly {\"ok\": true}. A failed check returns {\"ok\": false, "
        "\"reason\": \"one bounded remediation instruction\"}.\n"
        "Do not deny or undo the completed write.\n"
        "Hook input: $ARGUMENTS"
    )


def stop_prompt(preset: str) -> str:
    _validate_preset(preset)
    return (
        f"{MANAGED_MARKER}\n"
        "You are ADW's Stop verifier.\n"
        "Check stop_hook_active before doing any work. If it is true, return exactly {\"ok\": true}. "
        f"Read only the current session's bounded ADW candidate journal by running the exact helper {JOURNAL_READER_PATH} "
        "with the session_id from this hook input as its sole argument. Do not open state files directly, scan "
        "unrelated files, or read files not named by the helper output. "
        "Use read-only inspection. Do not scan unrelated files or edit files or settings.\n"
        "Batch all current prose and document candidates in one review. Empty or malformed ADW-owned input "
        "returns exactly {\"ok\": true}. A clean review returns exactly {\"ok\": true}. A failed review "
        "returns {\"ok\": false, \"reason\": \"one bounded remediation instruction\"}.\n"
        "Use the session_id from this hook input to locate only its journal.\n"
        "Hook input: $ARGUMENTS"
    )


def generated_hooks(preset: str) -> dict[str, list[dict[str, Any]]]:
    selected = _validate_preset(preset)
    if selected == "luna":
        command = _luna_command()
        return {
            "PostToolUse": [{
                "matcher": WRITE_MATCHER,
                "hooks": [{"type": "command", "command": command, "timeout": 120}],
            }],
            "Stop": [{
                "hooks": [{"type": "command", "command": command, "timeout": 120}],
            }],
        }
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
    if not isinstance(value, dict):
        return False
    if value.get("type") == "agent":
        prompt = value.get("prompt")
        return isinstance(prompt, str) and prompt.splitlines()[:1] == [MANAGED_MARKER]
    if value.get("type") == "command":
        command = value.get("command")
        if not isinstance(command, str):
            return False
        try:
            parts = shlex.split(command)
        except ValueError:
            return False
        return (
            len(parts) == 2
            and parts[0] == f"ADW_CLAUDE_MANAGED={MANAGED_MARKER}"
            and Path(parts[1]).is_absolute()
        )
    return False


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
    return _settings_snapshot(path)[1]


def _atomic_write(path: Path, text: str) -> None:
    target = Path(path)
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
        try:
            mode = os.lstat(target).st_mode & 0o777
        except FileNotFoundError:
            mode = 0o600
        if target.is_symlink() or (target.exists() and not stat.S_ISREG(os.lstat(target).st_mode)):
            raise ValueError(f"preset state leaf is not a regular file: {target}")
        temporary.chmod(mode)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _set_preset_unlocked(selected: str, target_settings: Path, target_preset: Path) -> str:
    base_hash, current = _settings_snapshot(target_settings)
    base_preset = _read_preset_unlocked(target_preset)
    rendered = json.dumps(settings_for_preset(current, selected), indent=2, sort_keys=True) + "\n"
    transaction = {
        "version": TRANSACTION_VERSION,
        "preset": selected,
        "base_preset": base_preset,
        "base_settings_hash": base_hash,
    }
    _atomic_write(
        _transaction_path(target_preset),
        json.dumps(transaction, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write(_canonical(target_settings), rendered)
    _atomic_write(_canonical(target_preset), selected + "\n")
    _transaction_path(target_preset).unlink(missing_ok=True)
    return selected


def set_preset(
    preset: str,
    *,
    settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> str:
    selected = _validate_preset(preset)
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    target_preset = _canonical(preset_path) if preset_path is not None else _canonical(globals()["preset_path"]())
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)
        return _set_preset_unlocked(selected, target_settings, target_preset)


def status(*, settings_path: str | Path | None = None, preset_path: str | Path | None = None, environment: Mapping[str, str] | None = None) -> dict[str, str]:
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    target_preset = _canonical(preset_path) if preset_path is not None else _canonical(globals()["preset_path"]())
    env = os.environ if environment is None else environment
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)
        selected = _read_preset_unlocked(target_preset)
        if selected is None:
            selected = _default_preset_unlocked(env, target_preset)
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
    target_settings = _canonical(settings_path) if settings_path is not None else _canonical(globals()["settings_path"]())
    target_preset = _canonical(preset_path) if preset_path is not None else _canonical(globals()["preset_path"]())
    fallback = "mixed"
    with _preset_lock(target_preset):
        _recover_unlocked(target_settings, target_preset)
        current = _read_preset_unlocked(target_preset) or "mixed"
        if current == "luna":
            _set_preset_unlocked(fallback, target_settings, target_preset)
            switched = True
        else:
            fallback = current
            switched = False
    bounded = " ".join(str(reason).split())[:MAX_FAILURE_MESSAGE]
    transition = f"Switched subsequent events to {fallback}." if switched else f"{fallback} remains configured."
    return {
        "preset": fallback,
        "switched": switched,
        "message": f"Luna {role} review unavailable: {bounded}. {transition}",
    }


def luna_review(
    request: object,
    role: str,
    *,
    provider: object | None = None,
    settings_path: str | Path | None = None,
    preset_path: str | Path | None = None,
) -> dict[str, Any]:
    if role not in {"comment", "prose", "document"}:
        raise ValueError("role must be comment, prose, or document")
    if provider is None:
        try:
            from .luna_provider import LunaJudge
        except ImportError:
            from luna_provider import LunaJudge
        provider = LunaJudge()
    try:
        result = provider.judge(request)
    except LunaUnavailable as exc:
        fallback = fallback_after_luna_failure(
            role, str(exc), settings_path=settings_path, preset_path=preset_path,
        )
        return {"ok": False, "reason": fallback["message"], "preset": fallback["preset"]}
    except Exception as exc:
        try:
            from .luna_storage import LunaProviderFailure
        except ImportError:
            from luna_storage import LunaProviderFailure
        if not isinstance(exc, LunaProviderFailure):
            raise
        fallback = fallback_after_luna_failure(
            role, str(exc), settings_path=settings_path, preset_path=preset_path,
        )
        return {"ok": False, "reason": fallback["message"], "preset": fallback["preset"]}
    return {"ok": True, "result": result}


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


if __name__ == "__main__":
    raise SystemExit(main())
