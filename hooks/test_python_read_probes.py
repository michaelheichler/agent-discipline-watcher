from __future__ import annotations

import shlex
import subprocess
import sys
import textwrap

import pytest

import pre_tool
from lib.python_payload import is_known_read_only_python


READ_PROBES = [
    pytest.param(textwrap.dedent("""\
        from pathlib import Path
        root = Path.cwd()
        for path in [
            root / '.codex/hooks.json',
            root / '.adw/install/plugin.json',
            root / '.adw/reports/turn.json',
        ]:
            print(path)
            print(path.read_text() if path.exists() else 'missing')
    """), id="report-files"),
    pytest.param(textwrap.dedent("""\
        from pathlib import Path
        root = Path.cwd()
        for path in [root / '.codex/config.toml', Path('.agent-discipline.json')]:
            if path.exists():
                print(path)
                for number, line in enumerate(path.read_text().splitlines(), 1):
                    if any(word in line.lower() for word in ['adw', 'hook', 'discipline']):
                        print(number, line)
    """), id="filtered-config-lines"),
]


@pytest.fixture
def read_tree(tmp_path):
    files = {
        '.codex/hooks.json': '{"adw": true}',
        '.adw/install/plugin.json': '{"name": "adw"}',
        '.adw/reports/turn.json': '[]',
        '.codex/config.toml': 'enabled = true\nadw = "installed"\n',
        '.agent-discipline.json': '{"hooks": true}',
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("source", READ_PROBES)
def test_read_probe_ast_is_accepted(source):
    assert is_known_read_only_python(source, isolated=True)


@pytest.mark.parametrize("source", READ_PROBES)
def test_python_tool_accepts_read_probe(source, read_tree):
    response = pre_tool.run({
        "tool_name": "Python",
        "cwd": str(read_tree),
        "tool_input": {"code": source},
    })

    assert response == {}


@pytest.mark.parametrize("source", READ_PROBES)
@pytest.mark.parametrize("options", [[], ["-I", "-S"]], ids=["normal", "isolated"])
def test_bash_heredoc_accepts_read_probe(source, options, read_tree):
    before = {path.relative_to(read_tree): path.read_bytes() for path in read_tree.rglob("*") if path.is_file()}
    executed = subprocess.run(
        [sys.executable, *options, "-c", source], cwd=read_tree,
        text=True, capture_output=True, check=False,
    )

    assert executed.returncode == 0, executed.stderr
    assert "adw" in executed.stdout
    assert {path.relative_to(read_tree): path.read_bytes() for path in read_tree.rglob("*") if path.is_file()} == before

    command = f"python3 {' '.join(options)} <<'PY'\n{source}PY"
    response = pre_tool.run({
        "tool_name": "Bash",
        "cwd": str(read_tree),
        "tool_input": {"command": command},
    }, {"ledger_root": str(read_tree / "ledger"), "state_root": str(read_tree / "state")})

    assert response == {}


def test_path_join_keeps_read_methods_available():
    source = "from pathlib import Path; print((Path.cwd() / 'data.txt').read_text())"

    assert is_known_read_only_python(source, isolated=True)


def test_normal_python_inline_read_is_allowed(read_tree):
    source = "from pathlib import Path; print(Path('.codex/hooks.json').read_text())"
    response = pre_tool.run({
        "tool_name": "Bash",
        "cwd": str(read_tree),
        "tool_input": {"command": f"python3 -c {shlex.quote(source)}"},
    }, {"ledger_root": str(read_tree / "ledger"), "state_root": str(read_tree / "state")})

    assert response == {}


@pytest.mark.parametrize("source", [
    "from pathlib import Path\nfor path in [Path('target.txt')]:\n    path.write_text('unreviewed')",
    "from pathlib import Path\nfor path in [Path('target.txt')]:\n    path.unlink()",
    "for print in [open]:\n    print('target.txt', 'w')",
    "for path in ['target.txt']:\n    run_user_supplied_code(path)",
    "from pathlib import Path; any(Path(name).write_text('unreviewed') for name in ['target.txt'])",
    "from pathlib import Path; any(name for name in [Path('target.txt').write_text('unreviewed')])",
    "from pathlib import Path; any(name for name in ['target.txt'] if Path(name).write_text('unreviewed'))",
    "from pathlib import Path; print((Path.cwd() / Path('target.txt').write_text('unreviewed')).read_text())",
])
def test_read_probe_constructs_do_not_hide_mutations_or_unknown_calls(source):
    assert not is_known_read_only_python(source, isolated=True)


@pytest.mark.parametrize("source", [
    "from pathlib import Path\nfor number, path in enumerate([Path('data.txt')]):\n    print(f'{number}: {path.read_text()}')",
    "from pathlib import Path; path = Path('data.txt'); print(any(path for path in [False])); print(path.read_text())",
    "from pathlib import Path; print(any(word in path.read_text() for path in [Path('data.txt')] for word in ['adw']))",
])
def test_read_probe_keeps_nested_types_and_generator_scope(source):
    assert is_known_read_only_python(source, isolated=True)


@pytest.mark.parametrize("source", [
    "from pathlib import Path\nfor reader in [Path('data.txt').read_text]:\n    print(reader())",
    "for name, reader in [('data.txt', open)]:\n    print(reader(name))",
    "print(any(open for open in [False]))",
    "from pathlib import Path; any(path for path in [Path('data.txt')]); print(path.read_text())",
])
def test_loop_bindings_preserve_alias_and_scope_guards(source):
    assert not is_known_read_only_python(source, isolated=True)


@pytest.mark.parametrize("command", [
    "printf 'print(1)' | python3",
    "python3 -c 'value = 1\nprint(value)'",
    "(\npython3 -c 'print(1)'\n)",
    "sh -c \"python3 -c 'print(1)'\"",
])
def test_normal_python_reads_keep_literal_shell_routes(command, read_tree):
    response = pre_tool.run({
        "tool_name": "Bash", "cwd": str(read_tree), "tool_input": {"command": command},
    }, {"ledger_root": str(read_tree / "ledger"), "state_root": str(read_tree / "state")})

    assert response == {}
