import json
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import venv
from pathlib import Path

import pytest

import pre_tool


CASES = [
    ("json", "import json; print(json.loads('{}'))"),
    ("pathlib", "from pathlib import Path; print(Path('data.txt').read_text())"),
]


def shadow_module(directory: Path, module: str) -> Path:
    marker = directory / "import-ran.txt"
    (directory / f"{module}.py").write_text(f"open({str(marker)!r}, 'w').write('import executed')\n", encoding="utf-8")
    (directory / "data.txt").write_text("readable", encoding="utf-8")
    return marker


@pytest.mark.parametrize("module,code", CASES)
def test_python_tool_rejects_project_module_execution(tmp_path, module, code):
    marker = shadow_module(tmp_path, module)
    result = pre_tool.run({"tool_name": "Python", "cwd": str(tmp_path), "tool_input": {"code": code}})
    if result == {}:
        subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, check=False)

    assert result.get("decision") == "block"
    assert not marker.exists()


@pytest.mark.parametrize("module,code", CASES)
def test_bash_gate_rejects_shadowed_imports_before_they_run(tmp_path, module, code):
    marker = shadow_module(tmp_path, module)
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    result = pre_tool.run({"tool_name": "Bash", "cwd": str(tmp_path), "tool_input": {"command": command}})
    if result == {}:
        subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, check=False)

    assert result.get("decision") == "block"
    assert "python3 -I -S" in result["reason"]
    assert not marker.exists()


def test_python_tool_rejects_transitive_stdlib_shadowing(tmp_path):
    marker = shadow_module(tmp_path, "fnmatch")
    result = pre_tool.run({
        "tool_name": "Python", "cwd": str(tmp_path),
        "tool_input": {"code": "from pathlib import Path; print(Path('data.txt').read_text())"},
    })

    assert result.get("decision") == "block"
    assert not marker.exists()


def test_python_tool_checks_inherited_pythonpath_without_importing_it(tmp_path, monkeypatch):
    directory = tmp_path / "modules"
    directory.mkdir()
    marker = shadow_module(directory, "json")
    monkeypatch.setenv("PYTHONPATH", str(directory))
    result = pre_tool.run({"tool_name": "Python", "cwd": str(tmp_path), "tool_input": {"code": "import json"}})

    assert result.get("decision") == "block"
    assert not marker.exists()


@pytest.mark.parametrize("tool", ["Python", "Bash"])
def test_installed_pretool_contract_blocks_shadowed_imports(tmp_path, tool):
    marker = shadow_module(tmp_path, "pathlib")
    code = "from pathlib import Path; print(Path('data.txt').read_text())"
    tool_input = {"code": code} if tool == "Python" else {"command": f"python3 -c {shlex.quote(code)}"}
    runner = Path(__file__).with_name("run.sh")
    response = subprocess.run(
        [str(runner), "PreToolUse"], cwd=tmp_path,
        input=json.dumps({"tool_name": tool, "cwd": str(tmp_path), "tool_input": tool_input}),
        env={**os.environ, "ADW_PYTHON": sys.executable}, text=True, capture_output=True, check=False,
    )

    assert response.returncode == 0, response.stderr
    assert json.loads(response.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert not marker.exists()


@pytest.mark.parametrize("module", ["json", "sitecustomize"])
def test_hook_startup_does_not_execute_inherited_pythonpath(tmp_path, module):
    modules = tmp_path / "modules"
    modules.mkdir()
    marker = shadow_module(modules, module)
    response = subprocess.run(
        [str(Path(__file__).with_name("run.sh")), "PreToolUse"], cwd=tmp_path,
        input=json.dumps({"tool_name": "Python", "cwd": str(tmp_path), "tool_input": {"code": "import json"}}),
        env={**os.environ, "ADW_PYTHON": sys.executable, "PYTHONPATH": str(modules)},
        text=True, capture_output=True, check=False,
    )

    assert response.returncode == 0, response.stderr
    assert json.loads(response.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert not marker.exists()


def test_hook_startup_ignores_an_untrusted_python_home(tmp_path):
    response = subprocess.run(
        [str(Path(__file__).with_name("run.sh")), "PreToolUse"], cwd=tmp_path,
        input=json.dumps({"tool_name": "Python", "cwd": str(tmp_path), "tool_input": {"code": "print(1)"}}),
        env={**os.environ, "ADW_PYTHON": sys.executable, "PYTHONHOME": str(tmp_path / "untrusted")},
        text=True, capture_output=True, check=False,
    )

    assert response.returncode == 0, response.stderr
    assert json.loads(response.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_isolation_keeps_the_sdk_worker_site_packages(tmp_path):
    runtime = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(runtime)
    executable = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site_query = subprocess.run(
        [str(executable), "-c", "import site; print(site.getsitepackages()[0])"],
        text=True, capture_output=True, check=True,
    )
    marker = tmp_path / "sdk-import.json"
    sdk = Path(site_query.stdout.strip()) / "openai_codex.py"
    sdk.write_text(
        f"import json, sys\nwith open({str(marker)!r}, 'w') as output:\n"
        "    json.dump({'no_site': sys.flags.no_site, 'source': __file__}, output)\n"
        "raise RuntimeError('local SDK import probe completed')\n", encoding="utf-8",
    )
    hook_source = Path(__file__).parent
    hooks = tmp_path / "installation" / "hooks"
    hooks.mkdir(parents=True)
    for filename in ("run.sh", "resolve-python.sh"):
        shutil.copy2(hook_source / filename, hooks / filename)
    shutil.copy2(hook_source.parent / ".python-version", hooks.parent / ".python-version")
    (hooks / "session_start.py").write_text(textwrap.dedent(f"""
        import json, sys
        from pathlib import Path
        sys.path.insert(0, {str(hook_source)!r})
        from lib.luna_provider import LunaJudge, LunaProviderFailure
        from lib.judge_contracts import JudgeRequest, ReviewKind
        sys.executable = {str(executable)!r}
        judge = LunaJudge(runtime_root=Path({str(tmp_path / "calls")!r}),
                          cache_root=Path({str(tmp_path / "cache")!r}),
                          auth_source=Path({str(tmp_path / "missing-auth")!r}))
        try:
            judge.judge(JudgeRequest(review_kind=ReviewKind.PATTERN, candidates=("candidate",),
                                     rule_name="test", rule_action="remove"))
        except LunaProviderFailure as error:
            print(json.dumps({{"no_site": sys.flags.no_site, "category": error.category}}))
    """), encoding="utf-8")

    response = subprocess.run(
        [str(hooks / "run.sh"), "SessionStart"], cwd=tmp_path,
        env={**os.environ, "ADW_PYTHON": sys.executable}, text=True, capture_output=True, check=False,
    )

    assert response.returncode == 0, response.stderr
    assert json.loads(response.stdout) == {"no_site": 1, "category": "internal"}
    assert json.loads(marker.read_text(encoding="utf-8")) == {"no_site": 0, "source": str(sdk)}


def test_isolated_path_read_succeeds_despite_project_shadowing(tmp_path):
    marker = shadow_module(tmp_path, "pathlib")
    code = "from pathlib import Path; print(Path('data.txt').read_text())"
    command = f"{shlex.quote(sys.executable)} -I -S -c {shlex.quote(code)}"
    result = pre_tool.run({"tool_name": "Bash", "cwd": str(tmp_path), "tool_input": {"command": command}})

    assert result == {}
    executed = subprocess.run([sys.executable, "-I", "-S", "-c", code], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout.strip() == "readable"
    assert not marker.exists()


@pytest.mark.parametrize("tool", ["Python", "Bash"])
def test_installed_pretool_contract_allows_trusted_path_reads(tmp_path, tool):
    (tmp_path / "data.txt").write_text("readable", encoding="utf-8")
    code = "from pathlib import Path; print(Path('data.txt').read_text())"
    tool_input = {"code": code} if tool == "Python" else {"command": f"python3 -I -S -c {shlex.quote(code)}"}
    response = subprocess.run(
        [str(Path(__file__).with_name("run.sh")), "PreToolUse"], cwd=tmp_path,
        input=json.dumps({"tool_name": tool, "cwd": str(tmp_path), "tool_input": tool_input}),
        env={**os.environ, "ADW_PYTHON": sys.executable}, text=True, capture_output=True, check=False,
    )

    assert response.returncode == 0, response.stderr
    assert json.loads(response.stdout) == {}


@pytest.mark.parametrize("command", [
    "python3 -I -S -c 'print(open(\"source.md\").read())' > copy.md",
    "python3 -I -S -c 'print(open(\"source.md\").read())' | tee copy.md",
    "python3 -I -S -c 'print(open(\"source.md\").read())' | cat > copy.md",
    "python3 -I -S <<'EOF' > copy.md\nprint(open('source.md').read())\nEOF",
    "printf \"print(open('source.md').read())\" | python3 -I -S | tee copy.md",
    "sh -c 'python3 -I -S -c \"print(1)\"' > copy.md",
    "(python3 -I -S -c 'print(1)'; echo done) > copy.md",
    "{ python3 -I -S -c 'print(1)'; } | tee copy.md",
    "(python3 -I -S -c 'print(1)'; echo }; echo done) > copy.md",
])
def test_read_only_python_output_cannot_write_unreviewed_content(tmp_path, command):
    result = pre_tool.run({"tool_name": "Bash", "cwd": str(tmp_path), "tool_input": {"command": command}})

    assert result.get("decision") == "block"
    assert "opaque_source_write" in result["reason"]
    assert "Write or Edit" in result["reason"]


@pytest.mark.parametrize("command", [
    "python3 -I -S -c 'print(1)' > /dev/null",
    "python3 -I -S -c 'print(1)'; printf 'The cache holds two rows.' > note.md",
    "python3 -ISc 'print(1)'",
])
def test_python_reads_keep_safe_shell_output_routes(command):
    assert pre_tool.run({"tool_name": "Bash", "tool_input": {"command": command}}) == {}


@pytest.mark.parametrize("command", [
    "python3 -c 'print(\"-I -S\")'",
    "python3 -c 'print(1)' -I -S",
    "python3 -I -W '-S' -c 'print(1)'",
    "python3 -S -X '-I' -c 'print(1)'",
    "python3 -I -S $EXTRA -c 'print(1)'",
    "python3 -ISc'open(\"target.md\",\"w\").write(\"unreviewed\")' -c 'print(1)'",
    "python3 -ISc'open(\"target.md\",\"w\").write(\"unreviewed\")'",
    "python3 -I -S -ic 'print(1)' <<'EOF'\nopen('target.md', 'w').write('unreviewed')\nEOF",
])
def test_isolation_flags_must_belong_to_the_python_startup_options(command):
    result = pre_tool.run({"tool_name": "Bash", "tool_input": {"command": command}})

    assert result.get("decision") == "block"
    assert "python3 -I -S" in result["reason"]


@pytest.mark.parametrize("command", [
    "python3 -I -S -c 'open(\"target.md\", \"w\").write(\"unreviewed\")'",
    "python3 -IS -c 'from pathlib import Path; Path(\"target.md\").write_text(\"unreviewed\")'",
    "python3 -I -S <<'EOF'\nopen('target.md', 'w').write('unreviewed')\nEOF",
    "printf \"open('target.md', 'w').write('unreviewed')\" | python3 -I -S",
])
def test_isolation_does_not_allow_python_file_mutations(command):
    result = pre_tool.run({"tool_name": "Bash", "tool_input": {"command": command}})

    assert result.get("decision") == "block"
    assert "Write or Edit" in result["reason"]
