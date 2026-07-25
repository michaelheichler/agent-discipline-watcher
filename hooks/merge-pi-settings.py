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
)


def has_legacy(value):
    return any(name in json.dumps(value, sort_keys=True) for name in LEGACY)


def prune(value):
    if isinstance(value, list):
        return [prune(item) for item in value if not has_legacy(item)]
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            pruned = prune(item)
            if not has_legacy(pruned):
                cleaned[key] = pruned
        return cleaned
    return value


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
