"""Centralized here so that the CLI paths, commits, and full-repo scopes all attach the same severities instead of each caller reimplementing gate resolution."""

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import bm25, config, render, scanner

SEVERITY_ORDER = {"block": 0, "would_block": 1, "release": 2}
# Excluded from the --commits hunk filter because file_too_long and its siblings report at line 1 no matter which line changed.
RANGE_EXEMPT_RULES = config.SCANNER_ALWAYS_BLOCKING_RULES | config.FIXED_OBSERVE_RULES


@dataclass(frozen=True, slots=True)
class _ReviewSource:
    root: Path
    path: Path
    relative: str
    config: dict
    base: str | None


def _review_source(path: Path, root: Path, base: str | None) -> _ReviewSource:
    return _ReviewSource(
        root=root,
        path=path,
        relative=_relative(path, root),
        config=config.effective_config(cwd=path),
        base=base,
    )


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


def _source_text(source: _ReviewSource) -> str | None:
    """Read from HEAD when a commit range is active, because the working tree may have moved past the range being reviewed."""
    if source.base is not None:
        return _head_text(source.root, source.relative, source.config)
    return scanner.read_scannable(source.path, source.config)


def _ranged_rows(rows: list[dict], relative: str, ranges: dict[str, list[tuple[int, int]]] | None) -> list[dict]:
    if ranges is None:
        return rows
    allowed = ranges.get(relative, [])
    return [
        row
        for row in rows
        if row["rule"] in RANGE_EXEMPT_RULES
        or any(first <= row["line"] <= last for first, last in allowed)
    ]


def _finding_row(row: dict, relative: str, cfg: dict) -> dict:
    return {
        "rule": row["rule"],
        "severity": config.resolve_outcome(row, cfg),
        "path": relative,
        "line": row["line"],
        "excerpt": row["snippet"],
        "hint": row["action"],
    }


def _scan_path(
    source: _ReviewSource,
    ranges: dict[str, list[tuple[int, int]]] | None,
) -> list[dict]:
    text = _source_text(source)
    if text is None:
        return []
    rows = _ranged_rows(scanner.scan_all(source.relative, text, source.config), source.relative, ranges)
    return [_finding_row(row, source.relative, source.config) for row in rows]


def _gitnexus(root: Path) -> str:
    executable = shutil.which("gitnexus")
    if executable is None:
        return "gitnexus: unavailable"
    try:
        result = subprocess.run(
            [executable, "status"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "gitnexus: stale"
    except OSError as exc:
        # Named instead of collapsed to "error", because a probe result an operator cannot act on is no better than none.
        return f"gitnexus: error ({exc})"
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        return f"gitnexus: error (exit {result.returncode}): {detail}"
    detail = result.stdout.strip().splitlines()
    return f"gitnexus: {detail[0]}" if detail else "gitnexus: available"


def run_review(args) -> tuple[list[dict], str, str, str | None]:
    """Scope resolved once here so that findings, revision, and the gitnexus probe all describe the exact same file set."""
    cwd = Path(getattr(args, "cwd", ".")).resolve()
    root, paths, scope, base = _scope(args, cwd)
    ranges = _changed_ranges(root, base) if base is not None else None
    findings = [
        row
        for path in paths
        for row in _scan_path(_review_source(path, root, base), ranges)
    ]
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
    """Reuses review scope resolution here so that search results and review findings can never drift onto different file sets."""
    cwd = Path(getattr(args, "cwd", ".")).resolve()
    root, paths, _, base = _scope(args, cwd)
    documents = []
    for path in paths:
        source = _review_source(path, root, base)
        text = _source_text(source)
        if text is not None:
            documents.extend(bm25.chunks(source.relative, text, bm25.CHUNK_LINES))
    return documents


def add_review_parser(subparsers) -> None:
    """Build the review subcommand once here, because bin/agent-discipline and bin/adw-cli had drifted apart wiring it twice."""
    parser = subparsers.add_parser("review", help="scan files, commits, or the repository")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--commits", type=int, metavar="N")
    parser.add_argument(
        "--format",
        choices=("text", "md", "json"),
        default="json",
        help="report format. JSON v1 fields: [rule,severity,path,line,excerpt,hint]",
    )
    parser.add_argument("--output", metavar="FILE")
    parser.add_argument("--gitnexus", action="store_true")
    parser.set_defaults(func=emit)


def emit(args) -> int:
    """Exit status reflects only block severity here so that CI fails on real violations without also failing on would-block observations."""
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


def _finding_documents(findings: list[dict]) -> list[dict]:
    return [
        {
            "text": f"{row['rule']} {row['excerpt']} {row['hint']}",
            "path": row["path"],
            "line": row["line"],
            "corpus": "finding",
        }
        for row in findings
    ]


def run_search(args) -> list[dict]:
    """Skip a corpus the caller did not ask for, because scanning both doubles the work when only one is wanted."""
    use_findings = args.findings or not args.code
    use_code = args.code or not args.findings
    documents = []
    if use_findings:
        findings, _, _, _ = run_review(args)
        documents.extend(_finding_documents(findings))
    if use_code:
        documents.extend(code_documents(args))
    return bm25.rank(args.query, documents)


def emit_search(args) -> int:
    """Print through stdout instead of returning rows, because a CLI subcommand's output must stay pipeable to other tools."""
    for row in run_search(args):
        first_line = row["text"].splitlines()[0] if row["text"] else ""
        print(
            f"{row['score']:.3f}\t{row['corpus']}\t"
            f"{row['path']}:{row.get('line', 1)}\t{first_line}"
        )
    return 0
