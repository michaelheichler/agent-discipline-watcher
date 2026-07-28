#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


LEGACY = (
    "punctuation-discipline",
    "english-for-agents",
    "clean-coder-discipline",
    "professional-agent-helper",
    "agent-discipline-watcher",
    "uncle-bobs-cc",
)
STALE_HOOK_COMMANDS = LEGACY + (
    "knowledge-based-search",
    "lean-ctx",
)
DROP = object()


def has_legacy(value):
    return any(name in json.dumps(value, sort_keys=True) for name in LEGACY)


def is_legacy_command(value):
    if not isinstance(value, dict):
        return False
    command = value.get("command")
    return isinstance(command, str) and any(name in command for name in STALE_HOOK_COMMANDS)


def prune(value):
    if is_legacy_command(value):
        return DROP
    if isinstance(value, list):
        cleaned = []
        for item in value:
            pruned = prune(item)
            if pruned is not DROP:
                cleaned.append(pruned)
        return cleaned
    if isinstance(value, dict):
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
    return value


def load_json(path):
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def watcher_hooks(skill_dir):
    snippet = Path(__file__).with_name("claude-settings.snippet.json")
    raw = snippet.read_text(encoding="utf-8").replace("__SKILL_DIR__", str(skill_dir))
    return json.loads(raw)["hooks"]


def merge(settings_path, skill_dir):
    settings = prune(load_json(settings_path))
    if settings is DROP:
        settings = {}
    hooks = settings.setdefault("hooks", {})
    for lifecycle, entries in watcher_hooks(skill_dir).items():
        hooks[lifecycle] = list(hooks.get(lifecycle, [])) + entries
    _write(settings_path, settings)


def remove_legacy(settings_path):
    """Drop path-based watcher entries so the plugin install is the only registration, returning whether anything changed."""
    original = load_json(settings_path)
    cleaned = prune(original)
    if cleaned is DROP:
        cleaned = {}
    _drop_emptied_lifecycles(original, cleaned)
    if cleaned == original:
        return False
    _write(settings_path, cleaned)
    return True


def _drop_emptied_lifecycles(original, cleaned):
    """Remove only the lifecycles this prune emptied, because a lifecycle the user left empty is not ours to delete."""
    before = original.get("hooks") if isinstance(original, dict) else None
    after = cleaned.get("hooks") if isinstance(cleaned, dict) else None
    if not isinstance(before, dict) or not isinstance(after, dict):
        return
    for lifecycle in list(after):
        if after[lifecycle] == [] and before.get(lifecycle):
            del after[lifecycle]


def _write(settings_path, settings):
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
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
