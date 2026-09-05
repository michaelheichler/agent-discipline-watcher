from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


WATCHER_MARKERS = (
    "ADW_CODEX_HOOK=1",
    "/agent-discipline-watcher/hooks/run.sh",
)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def replace_skill_dir(value: object, skill_dir: Path) -> object:
    if isinstance(value, str):
        return value.replace("__SKILL_DIR__", str(skill_dir))
    if isinstance(value, list):
        return [replace_skill_dir(item, skill_dir) for item in value]
    if isinstance(value, dict):
        return {key: replace_skill_dir(item, skill_dir) for key, item in value.items()}
    return value


def load_template(skill_dir: Path) -> dict:
    template_path = Path(__file__).with_name("codex-hooks.json")
    template = json.loads(template_path.read_text(encoding="utf-8"))
    resolved = replace_skill_dir(template, skill_dir)
    if not isinstance(resolved, dict) or not isinstance(resolved.get("hooks"), dict):
        raise ValueError("Codex hook template must contain a hooks object")
    return resolved


def is_watcher_group(group: object) -> bool:
    text = json.dumps(group, separators=(",", ":"))
    return any(marker in text for marker in WATCHER_MARKERS)


def merge(hooks_path: Path, skill_dir: Path) -> None:
    current = json.loads(hooks_path.read_text(encoding="utf-8")) if hooks_path.exists() else {}
    if not isinstance(current, dict):
        raise ValueError("Codex hooks file must contain an object")
    hooks = current.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Codex hooks file must contain a hooks object")

    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        kept = [group for group in groups if not is_watcher_group(group)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]

    for event, groups in load_template(skill_dir)["hooks"].items():
        hooks.setdefault(event, []).extend(groups)

    atomic_write(hooks_path, json.dumps(current, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hooks-json", required=True)
    parser.add_argument("--skill-dir", required=True)
    args = parser.parse_args()
    merge(Path(args.hooks_json).expanduser(), Path(args.skill_dir).expanduser())


if __name__ == "__main__":
    main()
