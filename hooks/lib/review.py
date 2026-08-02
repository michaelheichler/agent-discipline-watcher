"""Resolve review scopes and attach paths and severities to scanner findings."""

import shutil
import subprocess
import sys
from pathlib import Path

from . import config, render, scanner

SEVERITY_ORDER = {"block": 0, "would_block": 1, "release": 2}


def _run(args: list[str], cwd: Path, timeout: float = 10) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"command timed out: {' '.join(args)}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "command failed"
        raise ValueError(detail) from exc
    return result.stdout


def _root(cwd: Path) -> Path:
    try:
        return Path(_run(["git", "rev-parse", "--show-toplevel"], cwd).strip())
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"full review scope requires a git repository at {cwd}. Pass one or more paths."
        ) from exc


def _optional_root(cwd: Path) -> Path:
    try:
        return _root(cwd)
    except ValueError:
        return cwd


def _base(root: Path, commits: int) -> str:
    if commits < 1:
        raise ValueError("--commits must be a positive integer")
    try:
        return _run(["git", "rev-parse", f"HEAD~{commits}"], root).strip()
    except ValueError as exc:
        raise ValueError(
            f"cannot resolve HEAD~{commits}. The repository history may be shallow or shorter than requested."
        ) from exc


def _tracked_paths(root: Path) -> list[Path]:
    raw = _run(["git", "ls-files", "-z"], root)
    return [root / item for item in raw.split("\0") if item]


def _commit_paths(root: Path, base: str) -> list[Path]:
    raw = _run(
        ["git", "diff", "--diff-filter=ACMR", "--name-only", "-z", base, "HEAD"],
        root,
    )
    return [root / item for item in raw.split("\0") if item]


def _directory_paths(path: Path, root: Path) -> list[Path]:
    try:
        relative = path.relative_to(root)
        raw = _run(["git", "ls-files", "-z", "--", str(relative)], root)
        return [root / item for item in raw.split("\0") if item]
    except (OSError, ValueError):
        return [
            item
            for item in path.rglob("*")
            if item.is_file() and ".git" not in item.parts
        ]


def _explicit_paths(cwd: Path, values: list[str], root: Path) -> list[Path]:
    paths = []
    for value in values:
        path = (cwd / value).resolve()
        if not path.exists():
            raise ValueError(f"path does not exist: {path}")
        if path.is_dir():
            paths.extend(_directory_paths(path, root))
        else:
            paths.append(path)
    return paths


def _scope(args, cwd: Path) -> tuple[Path, list[Path], str, str | None]:
    commits = getattr(args, "commits", None)
    paths = list(getattr(args, "paths", []) or [])
    if commits is not None:
        root = _root(cwd)
        base = _base(root, commits)
        return root, _commit_paths(root, base), f"last {commits} commits", base
    if paths:
        root = _optional_root(cwd)
        return root, _explicit_paths(cwd, paths, root), "selected paths", None
    root = _root(cwd)
    return root, _tracked_paths(root), "full repository", None


def _hunk_range(line: str) -> tuple[int, int] | None:
    marker = line.split("+", 1)[1].split(" ", 1)[0]
    start, separator, size = marker.partition(",")
    count = int(size) if separator else 1
    if not count:
        return None
    first = int(start)
    return first, first + count - 1


def _parse_ranges(text: str) -> dict[str, list[tuple[int, int]]]:
    ranges: dict[str, list[tuple[int, int]]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            ranges.setdefault(current, [])
            continue
        if not current or not line.startswith("@@"):
            continue
        added = _hunk_range(line)
        if added is not None:
            ranges[current].append(added)
    return ranges


def _changed_ranges(root: Path, base: str) -> dict[str, list[tuple[int, int]]]:
    patch = _run(
        ["git", "diff", "--unified=0", "--no-ext-diff", base, "HEAD"],
        root,
    )
    return _parse_ranges(patch)


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _head_text(root: Path, relative: str, cfg: dict) -> str | None:
    try:
        text = _run(["git", "show", f"HEAD:{relative}"], root)
    except ValueError:
        return None
    return scanner.scannable_text(text, cfg)


def _scan_path(path: Path, context: tuple) -> list[dict]:
    root, ranges, from_head = context
    relative = _relative(path, root)
    cfg = config.effective_config(cwd=path)
    text = _head_text(root, relative, cfg) if from_head else scanner.read_scannable(path, cfg)
    if text is None:
        return []
    rows = scanner.scan_all(relative, text, cfg)
    if ranges is not None:
        allowed = ranges.get(relative, [])
        rows = [row for row in rows if any(first <= row["line"] <= last for first, last in allowed)]
    return [
        {
            "rule": row["rule"],
            "severity": config.resolve_outcome(row, cfg),
            "path": relative,
            "line": row["line"],
            "excerpt": row["snippet"],
            "hint": row["action"],
        }
        for row in rows
    ]


def _gitnexus(root: Path) -> str:
    executable = shutil.which("gitnexus")
    if executable is None:
        return "gitnexus: unavailable"
    try:
        result = subprocess.run(
            [executable, "status"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except subprocess.TimeoutExpired:
        return "gitnexus: stale"
    except (OSError, subprocess.CalledProcessError):
        return "gitnexus: error"
    detail = result.stdout.strip().splitlines()
    return f"gitnexus: {detail[0]}" if detail else "gitnexus: available"


def run_review(args) -> tuple[list[dict], str, str, str | None]:
    """Return scanner findings and report metadata for one resolved scope."""
    cwd = Path(getattr(args, "cwd", ".")).resolve()
    root, paths, scope, base = _scope(args, cwd)
    ranges = _changed_ranges(root, base) if base is not None else None
    context = (root, ranges, base is not None)
    findings = [row for path in paths for row in _scan_path(path, context)]
    findings.sort(
        key=lambda row: (
            SEVERITY_ORDER[row["severity"]],
            row["path"],
            row["line"],
            row["rule"],
        )
    )
    revision = _run(["git", "rev-parse", "HEAD"], root).strip() if base is not None else "working tree"
    metadata = _gitnexus(root) if getattr(args, "gitnexus", False) else None
    return findings, scope, revision, metadata


def code_documents(args) -> list[dict]:
    """Return bounded source documents from the same scope used by review."""
    from . import bm25

    cwd = Path(getattr(args, "cwd", ".")).resolve()
    root, paths, _, base = _scope(args, cwd)
    documents = []
    for path in paths:
        relative = _relative(path, root)
        cfg = config.effective_config(cwd=path)
        text = _head_text(root, relative, cfg) if base is not None else scanner.read_scannable(path, cfg)
        if text is not None:
            documents.extend(bm25.chunks(relative, text))
    return documents


def emit(args) -> int:
    """Write the selected report format and return a CI-ready finding status."""
    findings, scope, revision, metadata = run_review(args)
    renderers = {
        "text": lambda: render.render_text(findings, scope, revision),
        "md": lambda: render.render_md(findings, scope, revision),
        "json": lambda: render.render_json(findings),
    }
    output = renderers[args.format]()
    if metadata and args.format != "json":
        output += metadata + "\n"
    if getattr(args, "output", None):
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    if metadata and args.format == "json":
        print(metadata, file=sys.stderr)
    return 1 if any(item["severity"] == "block" for item in findings) else 0
