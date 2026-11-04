"""Checked in the source, because the user banned headless Claude and a subprocess call hides from every test of its caller."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
SCRIPT_TREES = ("hooks", "hosts")
SCRIPT_SUFFIXES = frozenset({".py", ".sh"})
PRINT_FLAGS = frozenset({"-p", "--print"})
SHELL_LAUNCH = re.compile(r"""\bclaude\w*["'}]*(?:\s+[^\s|;&]+)*?\s+(?:-p|--print)(?=[\s"']|$)""", re.IGNORECASE)
RETIRED_NAME = "claude_sonnet"
RETIRED_CONSTANT = re.compile(rf'[A-Z_]+ = "{RETIRED_NAME}\.sh"')
CONSTANT_HOME = "claude_presets.py"
DELETED_COMMAND = """
def claude_command(system: str) -> list[str]:
    binary = shutil.which("claude") or os.environ.get(EXEC_PATH_ENV, "")
    if not binary:
        raise CliUnavailable("the claude CLI is not on PATH")
    return [binary, "-p", "--model", MODEL, "--tools", "", "--system-prompt", system]
"""


def _shipped_scripts() -> tuple[Path, ...]:
    trees = [path for tree in SCRIPT_TREES for path in (REPO_ROOT / tree).rglob("*") if path.suffix in SCRIPT_SUFFIXES]
    return tuple(sorted(
        path for path in (*trees, *(REPO_ROOT / "bin").iterdir())
        if path.is_file() and not path.name.startswith("test_") and path.name != "conftest.py"
    ))


def _is_python(path: Path) -> bool:
    first_line = path.read_text(encoding="utf-8").partition("\n")[0]
    return path.suffix == ".py" or (first_line.startswith("#!") and "python" in first_line)


def _shell_launches(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if not line.lstrip().startswith("#") and SHELL_LAUNCH.search(line)]


def _docstring_nodes(tree: ast.Module) -> set[ast.AST]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return {
        node.body[0].value for node in ast.walk(tree)
        if isinstance(node, owners) and node.body and isinstance(node.body[0], ast.Expr)
    }


def _names_claude(value: str) -> bool:
    return value.rpartition("/")[2] == "claude"


def _may_run_claude(first: ast.expr) -> bool:
    """A literal program other than Claude rules the sequence out, because ps and git take -p too."""
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return True
    return first.value.startswith("-") or _names_claude(first.value)


def _passes_a_print_flag(node: ast.List | ast.Tuple) -> bool:
    flagged = any(isinstance(item, ast.Constant) and item.value in PRINT_FLAGS for item in node.elts)
    return flagged and _may_run_claude(node.elts[0])


def _python_launches(text: str) -> list[str]:
    tree = ast.parse(text)
    docstrings = _docstring_nodes(tree)
    strings = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in docstrings
    ]
    sequences = [node for node in ast.walk(tree) if isinstance(node, (ast.List, ast.Tuple)) and node.elts]
    argv = [ast.unparse(node) for node in sequences if _passes_a_print_flag(node)] if any(map(_names_claude, strings)) else []
    return argv + [value for value in strings if SHELL_LAUNCH.search(value)]


def _launches(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return _python_launches(text) if _is_python(path) else _shell_launches(text)


def _retired_mentions(path: Path) -> list[str]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if RETIRED_NAME in line]
    return [line for line in lines if not (path.name == CONSTANT_HOME and RETIRED_CONSTANT.fullmatch(line))]


def test_no_shipped_script_launches_headless_claude() -> None:
    found = {str(path.relative_to(REPO_ROOT)): launches for path in _shipped_scripts() if (launches := _launches(path))}

    assert found == {}


def test_no_shipped_script_names_the_retired_sonnet_handler_outside_its_one_constant() -> None:
    found = {str(path.relative_to(REPO_ROOT)): mentions for path in _shipped_scripts() if (mentions := _retired_mentions(path))}

    assert found == {}


@pytest.mark.parametrize("source", [
    pytest.param(DELETED_COMMAND, id="deleted-claude-command"),
    pytest.param(DELETED_COMMAND.replace('"-p"', '"--print"'), id="deleted-shape-with-the-long-flag"),
    pytest.param('run(["claude", "-p", prompt])', id="literal-argv"),
    pytest.param('run(("/usr/local/bin/claude", "--print"))', id="literal-absolute-argv"),
    pytest.param('FLAGS = ("-p", "--model")\nBINARY = which("claude")', id="flags-apart-from-the-binary"),
    pytest.param('run("claude -p hello", shell=True)', id="shell-string"),
])
def test_the_guard_recognises_a_python_launch(source: str) -> None:
    assert _python_launches(source)


@pytest.mark.parametrize("source", [
    pytest.param('BINARY = which("claude")\nrun(["/bin/ps", "-p", pid])', id="another-program-beside-claude"),
    pytest.param('BINARY = which("claude")\nrun([BINARY, "plugin", "install", name])', id="plugin-maintenance"),
    pytest.param('run([binary, "-p", pid])', id="print-flag-in-a-module-without-claude"),
    pytest.param('"""Never run claude -p, because the user banned it."""', id="docstring"),
])
def test_the_guard_leaves_other_python_alone(source: str) -> None:
    assert _python_launches(source) == []


@pytest.mark.parametrize("line", [
    pytest.param('claude -p "$prompt"', id="short-flag"),
    pytest.param("claude --model x --print", id="long-flag-after-another-flag"),
    pytest.param('"$CLAUDE_BIN" -p hello', id="binary-in-a-variable"),
    pytest.param('printf %s "$prompt" | claude -p', id="piped-prompt"),
])
def test_the_guard_recognises_a_shell_launch(line: str) -> None:
    assert _shell_launches(line) == [line]


@pytest.mark.parametrize("line", [
    pytest.param('claude plugin install "$plugin"', id="plugin-maintenance"),
    pytest.param('mkdir -p "$claude_home/skills"', id="another-program-naming-a-claude-folder"),
    pytest.param("claude plugin list && mkdir -p out", id="flag-of-the-next-command"),
    pytest.param("# never run claude -p here", id="comment"),
])
def test_the_guard_leaves_other_shell_alone(line: str) -> None:
    assert _shell_launches(line) == []
