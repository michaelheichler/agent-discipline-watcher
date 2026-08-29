#!/usr/bin/env python3
import argparse
import os
import re
import tempfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


# Only packages merged into this one belong here, because pruning a name we never absorbed deletes somebody else's hooks.
LEGACY = (
    "punctuation-discipline",
    "english-for-agents",
    "clean-coder-discipline",
    "professional-agent-helper",
    "uncle-bobs-cc",
    "agent-discipline-watcher",
)
# Excludes our own name: strip_fences already removes our fenced block explicitly, by markers, not by name.
PRIOR_PACKAGES = tuple(name for name in LEGACY if name != "agent-discipline-watcher")
HOOK_LIFECYCLES = {
    "ConfigChange",
    "InstructionsLoaded",
    "PostToolBatch",
    "PostToolUse",
    "PostToolUseFailure",
    "PreCompact",
    "PreToolUse",
    "SessionEnd",
    "SessionStart",
    "Stop",
    "SubagentStop",
    "TaskCompleted",
    "UserPromptSubmit",
}
FENCE_START = "# >>> agent-discipline-watcher >>>"
FENCE_END = "# <<< agent-discipline-watcher <<<"


def strip_fences(text: str) -> str:
    text = re.sub(
        re.escape(FENCE_START) + r"\n?(.*?)" + re.escape(FENCE_END) + r"\n?",
        lambda match: preserve_non_hook_tables(match.group(1)),
        text,
        flags=re.S,
    )
    for name in PRIOR_PACKAGES:
        text = re.sub(rf"# >>> {re.escape(name)} >>>.*?# <<< {re.escape(name)} <<<\n?", "", text, flags=re.S)
    return text


def _mentions_legacy(text: str) -> bool:
    # Bounded, because a bare substring check also strips a differently-named fork.
    return any(
        re.search(rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])", text)
        for name in LEGACY
    )


def preserve_non_hook_tables(text: str) -> str:
    kept = []
    for chunk in re.split(r"(?=^\[)", text, flags=re.M):
        stripped = chunk.lstrip()
        if not stripped:
            continue
        if stripped.startswith("[[hooks.") or stripped.startswith("[hooks"):
            continue
        kept.append(chunk)
    return "".join(kept)


def strip_legacy_tables(text: str) -> str:
    tables = re.split(r"(?=^\[\[hooks\.[A-Za-z]+\]\])", text, flags=re.M)
    kept = []
    for table in tables:
        if not table.lstrip().startswith("[[hooks."):
            kept.append(table)
            continue
        table, trailer = split_hook_table_trailer(table)
        if not _mentions_legacy(table):
            kept.append(table + trailer)
            continue
        parts = re.split(r"(?=^\[\[hooks\.[A-Za-z]+\.hooks\]\])", table, flags=re.M)
        head = parts[0]
        hook_parts = [part for part in parts[1:] if not _mentions_legacy(part)]
        if hook_parts:
            kept.append(head + "".join(hook_parts))
        kept.append(trailer)
    return "".join(kept)


def split_hook_table_trailer(table: str) -> tuple[str, str]:
    lines = table.splitlines(keepends=True)
    header = re.match(r"\[\[hooks\.([A-Za-z]+)\]\]", lines[0])
    lifecycle = header.group(1) if header else ""
    own_hooks_array = f"[[hooks.{lifecycle}.hooks]]"
    for index, line in enumerate(lines[1:], start=1):
        if line.startswith("[") and not line.startswith(own_hooks_array):
            return "".join(lines[:index]), "".join(lines[index:])
    return table, ""


def strip_legacy_inline_array(line: str) -> str:
    if "[" not in line or "]" not in line:
        return line
    match = re.match(r"^\s*([A-Za-z]+)\s*=\s*\[(.*)\]\s*$", line)
    if not match or match.group(1) not in HOOK_LIFECYCLES:
        return line
    lifecycle = match.group(1)
    items = re.findall(r"\{[^{}]*\}", match.group(2))
    kept = [item for item in items if not _mentions_legacy(item)]
    if not kept:
        return ""
    blocks = []
    for item in kept:
        command = re.search(r'command\s*=\s*"([^"]+)"', item)
        if command:
            blocks.append(
                f'[[hooks.{lifecycle}]]\n'
                f'[[hooks.{lifecycle}.hooks]]\n'
                'type = "command"\n'
                f'command = "{command.group(1)}"'
            )
    return "\n".join(blocks)


def strip_stale_inline_hook_arrays(text: str) -> str:
    lines = []
    for line in text.splitlines():
        line = strip_legacy_inline_array(line)
        if line:
            lines.append(line)
    return "\n".join(lines) + "\n"


def _next_nonblank(lines: list[str], index: int) -> str:
    for candidate in lines[index + 1 :]:
        if candidate.strip():
            return candidate.strip()
    return ""


def _is_empty_hook_header(line: str, lines: list[str], index: int) -> bool:
    if not re.match(r"^\s*\[\[hooks\.[A-Za-z]+\]\]\s*$", line):
        return False
    next_line = _next_nonblank(lines, index)
    if not next_line or re.match(r"^\[\[hooks\.[A-Za-z]+\]\]$", next_line):
        return True
    return next_line.startswith("[") and not next_line.startswith("[[hooks.")


def strip_empty_hook_headers(text: str) -> str:
    lines = text.splitlines()
    kept = [line for index, line in enumerate(lines) if not _is_empty_hook_header(line, lines, index)]
    return "\n".join(kept) + "\n"


def read_snippet(skill_dir: Path) -> str:
    snippet = Path(__file__).with_name("codex-config.snippet.toml")
    return snippet.read_text(encoding="utf-8").replace("__SKILL_DIR__", str(skill_dir))


def require_toml_parser() -> None:
    """Refuse to merge without a parser, because skipping validation would let a clobbered config install silently."""
    if tomllib is None:
        raise RuntimeError(
            "Codex merge needs python3.11 or newer: tomllib is unavailable, so the merged "
            "config cannot be validated and the merge is refused rather than risking your config."
        )


def validate_toml(text: str) -> None:
    require_toml_parser()
    tomllib.loads(text)


def validate_preserved_sections(before: str, after: str) -> None:
    require_toml_parser()
    if not before.strip():
        return
    before_data = tomllib.loads(before)
    after_data = tomllib.loads(after)
    changed = [
        key
        for key, value in before_data.items()
        if key != "hooks" and after_data.get(key) != value
    ]
    if changed:
        names = ", ".join(sorted(changed))
        raise ValueError(f"merge changed unrelated top-level sections: {names}")


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


def merge(config_path: Path, skill_dir: Path) -> None:
    current = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    current = strip_empty_hook_headers(strip_stale_inline_hook_arrays(strip_legacy_tables(strip_fences(current))))
    block = FENCE_START + "\n" + read_snippet(skill_dir).rstrip() + "\n" + FENCE_END + "\n"
    if current and not current.endswith("\n"):
        current += "\n"
    merged = re.sub(r"\n{3,}", "\n\n", current.rstrip() + "\n\n" + block)
    validate_toml(merged)
    validate_preserved_sections(current, merged)
    atomic_write(config_path, merged)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--skill-dir", required=True)
    args = parser.parse_args()
    merge(Path(args.config).expanduser(), Path(args.skill_dir).expanduser())


if __name__ == "__main__":
    main()
