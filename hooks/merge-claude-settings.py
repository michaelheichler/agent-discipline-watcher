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
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True)
    parser.add_argument("--skill-dir", required=True)
    args = parser.parse_args()
    merge(Path(args.settings).expanduser(), Path(args.skill_dir).expanduser())


if __name__ == "__main__":
    main()
