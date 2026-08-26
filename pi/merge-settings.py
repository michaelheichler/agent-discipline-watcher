#!/usr/bin/env python3
import argparse
import json
import os
import tempfile
from pathlib import Path

# Keep only packages merged into this one because pruning any other name deletes another package's extension.
LEGACY = (
    "punctuation-discipline",
    "english-for-agents",
    "clean-coder-discipline",
    "professional-agent-helper",
    "uncle-bobs-cc",
    "agent-discipline-watcher",
)
EXTENSION_KEY = "extensions"
EXTENSION_DIR = Path("pi") / "extensions" / "agent-discipline-watcher"
ENTRY_FILE = EXTENSION_DIR / "index.ts"


def has_legacy(value: object) -> bool:
    return any(name in json.dumps(value, sort_keys=True) for name in LEGACY)


def extension_entry(skill_dir: Path) -> str:
    return str((skill_dir / ENTRY_FILE).resolve())


def is_watcher_entry(item: object, skill_dir: Path | None = None) -> bool:
    if isinstance(item, str):
        if has_legacy(item):
            return True
        if skill_dir is not None and item == extension_entry(skill_dir):
            return True
        return "agent-discipline-watcher" in item and item.endswith("index.ts")
    return has_legacy(item)


def prune(value: dict) -> dict:
    """Drop watcher extension entries only, because unrelated settings that merely mention a name are user data."""
    cleaned = dict(value)
    entries = cleaned.get(EXTENSION_KEY)
    if isinstance(entries, list):
        cleaned[EXTENSION_KEY] = [item for item in entries if not has_legacy(item)]
    return cleaned


def load_json(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write(path: Path, text: str) -> None:
    # Resolved, because os.replace on a symlink path destroys the link instead of its target.
    target_path = path.resolve() if path.is_symlink() else path
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


def merge(settings_path: Path, skill_dir: Path, *, remove: bool = False) -> None:
    settings = prune(load_json(settings_path))
    target = extension_entry(skill_dir)
    extensions = settings.get(EXTENSION_KEY, [])
    if not isinstance(extensions, list):
        extensions = []

    kept = [item for item in extensions if not is_watcher_entry(item, skill_dir)]
    if not remove:
        kept.append(target)

    if kept:
        settings[EXTENSION_KEY] = kept
    elif EXTENSION_KEY in settings:
        del settings[EXTENSION_KEY]

    atomic_write(
        settings_path,
        json.dumps(settings, indent=2, sort_keys=True) + "\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Register the OMP extension in settings.json")
    parser.add_argument("--settings", required=True)
    parser.add_argument("--skill-dir", required=True)
    parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove watcher extension entries without adding a new one",
    )
    args = parser.parse_args()
    merge(
        Path(args.settings).expanduser(),
        Path(args.skill_dir).expanduser(),
        remove=args.remove,
    )


if __name__ == "__main__":
    main()
