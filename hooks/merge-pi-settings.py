#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


# Only packages merged into this one belong here, because pruning a name we never absorbed deletes somebody else's extension.
LEGACY = (
    "punctuation-discipline",
    "english-for-agents",
    "clean-coder-discipline",
    "professional-agent-helper",
    "uncle-bobs-cc",
    "agent-discipline-watcher",
)
EXTENSION_KEY = "extensions"


def has_legacy(value):
    return any(name in json.dumps(value, sort_keys=True) for name in LEGACY)


def prune(value):
    """Drop watcher extension entries only, because unrelated settings that merely mention a name are user data."""
    if not isinstance(value, dict):
        return value
    cleaned = dict(value)
    entries = cleaned.get(EXTENSION_KEY)
    if isinstance(entries, list):
        cleaned[EXTENSION_KEY] = [item for item in entries if not has_legacy(item)]
    return cleaned


def load_json(path):
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def merge(settings_path, skill_dir):
    settings = prune(load_json(settings_path))
    extensions = settings.setdefault("extensions", [])
    extensions.append(str(skill_dir / "pi" / "extensions" / "agent-discipline-watcher" / "index.ts"))
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
