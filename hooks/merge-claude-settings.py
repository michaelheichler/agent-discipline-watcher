#!/usr/bin/env python3
import argparse
import json
import os
import re
import tempfile
from pathlib import Path


# Only packages merged into this one belong here, because pruning a name we never absorbed deletes somebody else's hooks.
LEGACY = (
    "punctuation-discipline",
    "english-for-agents",
    "clean-coder-discipline",
    "professional-agent-helper",
    "agent-discipline-watcher",
    "uncle-bobs-cc",
)
DROP = object()

# Shape-based, because a skill dir is not guaranteed to spell out the package name.
_WATCHER_HOOK_COMMAND_RE = re.compile(r'/hooks/run\.sh"?\s+[A-Za-z]+\Z')


def has_legacy(value) -> bool:
    return any(name in json.dumps(value, sort_keys=True) for name in LEGACY)


def is_watcher_hook_command(value) -> bool:
    if not isinstance(value, dict):
        return False
    command = value.get("command")
    return isinstance(command, str) and bool(_WATCHER_HOOK_COMMAND_RE.search(command))


def is_legacy_command(value) -> bool:
    if not isinstance(value, dict):
        return False
    command = value.get("command")
    is_named_legacy = isinstance(command, str) and any(name in command for name in LEGACY)
    return is_named_legacy or is_watcher_hook_command(value)


def _prune_list(value: list) -> list:
    cleaned = []
    for item in value:
        pruned = prune(item)
        if pruned is not DROP:
            cleaned.append(pruned)
    return cleaned


def _prune_dict(value: dict) -> object:
    cleaned = {}
    for key, item in value.items():
        pruned = prune(item)
        if pruned is not DROP:
            cleaned[key] = pruned
    if "hooks" in cleaned and isinstance(cleaned["hooks"], list) and not cleaned["hooks"]:
        return DROP
    if not cleaned and has_legacy(value):
        return DROP
    return cleaned


def prune(value) -> object:
    if is_legacy_command(value):
        return DROP
    if isinstance(value, list):
        return _prune_list(value)
    if isinstance(value, dict):
        return _prune_dict(value)
    return value


def load_json(path) -> object:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def watcher_hooks(skill_dir) -> dict[str, list[dict[str, object]]]:
    manifest = Path(__file__).with_name("hooks.json")
    raw = manifest.read_text(encoding="utf-8").replace("${CLAUDE_PLUGIN_ROOT}", str(skill_dir))
    return json.loads(raw)["hooks"]


def merge(settings_path, skill_dir) -> None:
    settings = prune(load_json(settings_path))
    if settings is DROP:
        settings = {}
    hooks = settings.setdefault("hooks", {})
    for lifecycle, entries in watcher_hooks(skill_dir).items():
        hooks[lifecycle] = list(hooks.get(lifecycle, [])) + entries
    _write(settings_path, settings)


def remove_legacy(settings_path) -> bool:
    original = load_json(settings_path)
    cleaned = prune(original)
    if cleaned is DROP:
        cleaned = {}
    _drop_emptied_lifecycles(original, cleaned)
    if cleaned == original:
        return False
    _write(settings_path, cleaned)
    return True


def _drop_emptied_lifecycles(original, cleaned) -> None:
    """Remove only the lifecycles this prune emptied, because a lifecycle the user left empty is not ours to delete."""
    before = original.get("hooks") if isinstance(original, dict) else None
    after = cleaned.get("hooks") if isinstance(cleaned, dict) else None
    if not isinstance(before, dict) or not isinstance(after, dict):
        return
    for lifecycle in list(after):
        if after[lifecycle] == [] and before.get(lifecycle):
            del after[lifecycle]


def _write(settings_path, settings) -> None:
    # Resolved, because os.replace on a symlink path destroys the link instead of its target.
    target_path = settings_path.resolve() if settings_path.is_symlink() else settings_path
    text = json.dumps(settings, indent=2, sort_keys=True) + "\n"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    mode = target_path.stat().st_mode & 0o777 if target_path.exists() else 0o600
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.chmod(mode)
        os.replace(temporary_path, target_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True)
    parser.add_argument("--skill-dir")
    parser.add_argument(
        "--remove-legacy",
        action="store_true",
        help="strip path-based watcher hooks and add nothing, for migrating to the plugin install",
    )
    args = parser.parse_args()
    settings_path = Path(args.settings).expanduser()
    if args.remove_legacy:
        remove_legacy(settings_path)
        return
    if not args.skill_dir:
        parser.error("--skill-dir is required unless --remove-legacy is given")
    merge(settings_path, Path(args.skill_dir).expanduser())


if __name__ == "__main__":
    main()
