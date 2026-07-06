#!/usr/bin/env python3
import argparse
import os
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


LEGACY = (
    "punctuation-discipline",
    "english-for-agents",
    "clean-coder-discipline",
    "professional-agent-helper",
    "agent-discipline-watcher",
)
STALE_HOOK_COMMANDS = LEGACY + (
    "knowledge-based-search",
    "lean-ctx",
)
HOOK_LIFECYCLES = {
    "PreCompact",
    "PreToolUse",
    "PostToolUse",
    "SessionEnd",
    "SessionStart",
    "Stop",
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
    for name in LEGACY[:-1]:
        text = re.sub(rf"# >>> {re.escape(name)} >>>.*?# <<< {re.escape(name)} <<<\n?", "", text, flags=re.S)
    return text


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
        if not any(name in table for name in STALE_HOOK_COMMANDS):
            kept.append(table + trailer)
            continue
        parts = re.split(r"(?=^\[\[hooks\.[A-Za-z]+\.hooks\]\])", table, flags=re.M)
        head = parts[0]
        hook_parts = [part for part in parts[1:] if not any(name in part for name in STALE_HOOK_COMMANDS)]
        if hook_parts:
            kept.append(head + "".join(hook_parts))
        kept.append(trailer)
    return "".join(kept)


def split_hook_table_trailer(table: str) -> tuple[str, str]:
    lines = table.splitlines(keepends=True)
    for index, line in enumerate(lines[1:], start=1):
        if line.startswith("[") and not line.startswith("[[hooks."):
            return "".join(lines[:index]), "".join(lines[index:])
    return table, ""


def strip_legacy_inline_array(line: str) -> str:
    if not any(name in line for name in STALE_HOOK_COMMANDS) or "[" not in line or "]" not in line:
        return line
    match = re.match(r"^\s*([A-Za-z]+)\s*=\s*\[(.*)\]\s*$", line)
    if not match or match.group(1) not in HOOK_LIFECYCLES:
        return line
    lifecycle = match.group(1)
    items = re.findall(r"\{[^{}]*\}", match.group(2))
    kept = [item for item in items if not any(name in item for name in STALE_HOOK_COMMANDS)]
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


def strip_empty_hook_headers(text: str) -> str:
    lines = text.splitlines()
    kept = []
    for index, line in enumerate(lines):
        if re.match(r"^\s*\[\[hooks\.[A-Za-z]+\]\]\s*$", line):
            next_line = ""
            for candidate in lines[index + 1:]:
                if candidate.strip():
                    next_line = candidate.strip()
                    break
            if not next_line or re.match(r"^\[\[hooks\.[A-Za-z]+\]\]$", next_line):
                continue
            if next_line.startswith("[") and not next_line.startswith("[[hooks."):
                continue
        kept.append(line)
    return "\n".join(kept) + "\n"


def read_snippet(skill_dir: Path) -> str:
    snippet = Path(__file__).with_name("codex-config.snippet.toml")
    return snippet.read_text(encoding="utf-8").replace("__SKILL_DIR__", str(skill_dir))


def validate_toml(text: str) -> None:
    if tomllib is not None:
        tomllib.loads(text)


def merge(config_path: Path, skill_dir: Path) -> None:
    current = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    current = strip_empty_hook_headers(strip_stale_inline_hook_arrays(strip_legacy_tables(strip_fences(current))))
    block = FENCE_START + "\n" + read_snippet(skill_dir).rstrip() + "\n" + FENCE_END + "\n"
    if current and not current.endswith("\n"):
        current += "\n"
    merged = re.sub(r"\n{3,}", "\n\n", current.rstrip() + "\n\n" + block)
    validate_toml(merged)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(merged, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--skill-dir", required=True)
    args = parser.parse_args()
    merge(Path(args.config).expanduser(), Path(args.skill_dir).expanduser())


if __name__ == "__main__":
    main()
